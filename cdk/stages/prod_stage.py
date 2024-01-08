import typing

import aws_cdk
import constructs
import tbg_cdk
from aws_cdk import aws_iam, aws_ec2

import cdk.stacks.application_stack
from cdk.aws_config import AwsConfig


class ProdAlarmNotificationFunctionSecurityGroupFactory:
    def create(
        self,
        scope: constructs.Construct,
        id: str,
        *,
        namer: tbg_cdk.IResourceNamer,
        vpc: aws_ec2.IVpc,
    ) -> aws_ec2.ISecurityGroup:
        sg = aws_ec2.SecurityGroup(
            scope=scope,
            id=id,
            allow_all_outbound=True,
            description="Alarm notification function security group.",
            security_group_name=namer.get_name(
                "AlarmNotificationFunctionSecurityGroup"
            ),
            vpc=vpc,
        )

        aws_cdk.Tags.of(sg).add(
            key="Name", value=namer.get_name("AlarmNotificationFunctionSecurityGroup")
        )

        return sg


class ProdStage(aws_cdk.Stage):
    def __init__(
        self,
        scope: constructs.Construct,
        id: str,
        *,
        aws_config: AwsConfig,
        sentry_ingest_ips: typing.Sequence[str],
        slack_api_ips: typing.Sequence[str],
        **kwargs,
    ):
        super().__init__(scope=scope, id=id, **kwargs)

        namer = tbg_cdk.ResourceNamer(["Prod", "Prv", "UE1"])

        self._create_permissions_boundary_managed_policy(
            aws_config=aws_config, namer=namer
        )

        self._create_stack(
            aws_config=aws_config,
            namer=namer,
        )

        aws_cdk.Tags.of(self).add("Environment", "Production")

    def _create_permissions_boundary_managed_policy(
        self, aws_config: AwsConfig, namer: tbg_cdk.IResourceNamer
    ) -> None:
        self.permissions_boundary = aws_iam.ManagedPolicy(
            scope=self,
            id="PermissionsBoundary",
            description="Permissions boundary for the alarm notifier stack",
            managed_policy_name=namer.get_name("PermissionsBoundary"),
            statements=[
                aws_iam.PolicyStatement(
                    actions=[
                        "*",
                    ],
                    conditions={
                        "StringEquals": {
                            "aws:ResourceTag/ApplicationName": "Alarm Notifier",
                            "aws:ResourceTag/Environment": "Production",
                        }
                    },
                    effect=aws_iam.Effect.ALLOW,
                    resources=["*"],
                    sid="AllowApplicationSelfService",
                ),
                aws_iam.PolicyStatement(
                    actions=[
                        "ec2:AssignPrivateIpAddresses",
                        "ec2:CreateNetworkInterface",
                        "ec2:DeleteNetworkInterface",
                        "ec2:DescribeNetworkInterfaces",
                        "ec2:UnassignPrivateIpAddresses",
                    ],
                    conditions={
                        "ArnEquals": {
                            "ec2:Vpc": self.stack.format_arn(
                                resource="vpc",
                                service="ec2",
                                resource_name=aws_config.vpc_id,
                            )
                        }
                    },
                    effect=aws_iam.Effect.ALLOW,
                    resources=["*"],
                    sid="AllowLambdaVpc",
                ),
                aws_iam.PolicyStatement(
                    actions=["dynamodb:*"],
                    effect=aws_iam.Effect.ALLOW,
                    resources=["*"],
                    sid="AllowDynamoAccessBecauseItDoesNotSupportAbac",
                ),
                aws_iam.PolicyStatement(
                    actions=[
                        "secretsmanager:DescribeSecret",
                        "secretsmanager:GetSecretValue",
                    ],
                    effect=aws_iam.Effect.ALLOW,
                    resources=[
                        aws_config.sentry_dsn_secret_arn,
                        aws_config.slack_alarm_notifier_oauth_token_secret_arn,
                    ],
                    sid="AllowReadingSharedSecrets",
                ),
                aws_iam.PolicyStatement(
                    actions=[
                        "iam:CreateRole",
                        "iam:CreateUser",
                        "iam:PutRolePermissionsBoundary",
                        "iam:PutUserPermissionsBoundary",
                    ],
                    conditions={
                        "ArnNotEquals": {
                            "iam:PermissionsBoundary": aws_cdk.Arn.format(
                                components=aws_cdk.ArnComponents(
                                    resource="policy",
                                    service="iam",
                                    resource_name=namer.get_name("PermissionsBoundary"),
                                ),
                                stack=self.stack,
                            )
                        }
                    },
                    effect=aws_iam.Effect.DENY,
                    resources=["*"],
                    sid="CreateOrChangeOnlyWithPermissionsBoundary",
                ),
                aws_iam.PolicyStatement(
                    actions=[
                        "iam:CreatePolicyVersion",
                        "iam:DeletePolicy",
                        "iam:DeletePolicyVersion",
                        "iam:SetDefaultPolicyVersion",
                    ],
                    effect=aws_iam.Effect.DENY,
                    resources=[
                        aws_cdk.Arn.format(
                            components=aws_cdk.ArnComponents(
                                resource="policy",
                                service="iam",
                                region="",
                                resource_name=namer.get_name("PermissionsBoundary"),
                            ),
                            stack=self.stack,
                        )
                    ],
                    sid="NoPermissionBoundaryPolicyEdit",
                ),
            ],
        )

    def _create_stack(
        self, namer: tbg_cdk.IResourceNamer, aws_config: AwsConfig
    ) -> None:
        self.stack = cdk.stacks.application_stack.ApplicationStack(
            scope=self,
            id="AlarmNotifier",
            alarm_notification_function_security_group_factory=ProdAlarmNotificationFunctionSecurityGroupFactory(),
            namer=namer.with_prefix("AlarmNotifier"),
            permissions_boundary=self.permissions_boundary,
            sentry_dns_secret_complete_arn=aws_config.sentry_dsn_secret_arn,
            sentry_env="prod",
            slack_alarm_notifier_oauth_token_secret_complete_arn=aws_config.slack_alarm_notifier_oauth_token_secret_arn,
            stack_name=namer.get_name("AlarmNotifier"),
            vpc_id=aws_config.vpc_id,
        )
