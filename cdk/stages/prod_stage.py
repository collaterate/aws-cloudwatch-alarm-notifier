import aws_cdk
import cdk_nag
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
        self, scope: constructs.Construct, id: str, *, aws_config: AwsConfig, **kwargs
    ):
        super().__init__(scope=scope, id=id, **kwargs)

        namer = tbg_cdk.ResourceNamer(["Prod", "Prv", "UE1"])

        self._create_stack(namer=namer, aws_config=aws_config)

        self._create_permissions_boundary_managed_policy(
            namer=namer, secrets_manager_key_arn=aws_config.secrets_manager_key_arn
        )

        aws_iam.PermissionsBoundary.of(self.stack).apply(self.permissions_boundary)

        aws_cdk.Tags.of(self).add("Environment", "Production")

    def _create_stack(
        self, namer: tbg_cdk.IResourceNamer, aws_config: AwsConfig
    ) -> None:
        self.stack = cdk.stacks.application_stack.ApplicationStack(
            scope=self,
            id="AlarmNotifier",
            alarm_notification_function_security_group_factory=ProdAlarmNotificationFunctionSecurityGroupFactory(),
            namer=namer.with_prefix("AlarmNotifier"),
            sentry_dns_secret_complete_arn=aws_config.sentry_dsn_secret_arn,
            sentry_env="prod",
            slack_alarm_notifier_oauth_token_secret_complete_arn=aws_config.slack_alarm_notifier_oauth_token_secret_arn,
            stack_name=namer.get_name("AlarmNotifier"),
            vpc_id=aws_config.vpc_id,
        )

    def _create_permissions_boundary_managed_policy(
        self, namer: tbg_cdk.IResourceNamer, secrets_manager_key_arn: str
    ) -> None:
        self.permissions_boundary = aws_iam.ManagedPolicy(
            scope=self.stack,
            id="PermissionsBoundary",
            description="Permissions boundary for the alarm notifier stack",
            managed_policy_name=namer.get_name("PermissionsBoundary"),
            statements=[
                aws_iam.PolicyStatement(actions=["*"], resources=["*"]),
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
                ),
                aws_iam.PolicyStatement(
                    actions=[
                        "iam:DeleteRolePermissionsBoundary",
                        "iam:DeleteUserPermissionsBoundary",
                    ],
                    effect=aws_iam.Effect.DENY,
                    resources=["*"],
                ),
                aws_iam.PolicyStatement(
                    actions=[
                        "secretsmanager:DescribeSecret",
                        "secretsmanager:GetSecretValue",
                    ],
                    effect=aws_iam.Effect.DENY,
                    not_resources=[
                        self.stack.app.alarm_notification_sentry_dsn_secret.secret_full_arn,
                        self.stack.app.alarm_notification_slack_oauth_secret.secret_full_arn,
                    ],
                ),
                aws_iam.PolicyStatement(
                    actions=["kms:Decrypt"],
                    effect=aws_iam.Effect.DENY,
                    not_resources=[secrets_manager_key_arn, self.stack.app.key.key_arn],
                ),
                aws_iam.PolicyStatement(
                    not_actions=[
                        "ec2:CreateNetworkInterface",
                        "ec2:DescribeNetworkInterfaces",
                        "ec2:DeleteNetworkInterface",
                        "ec2:AssignPrivateIpAddresses",
                        "ec2:UnassignPrivateIpAddresses",
                        "kms:Decrypt",
                        "secretsmanager:DescribeSecret",
                        "secretsmanager:GetSecretValue",
                        "dynamodb:*",  # Does not support ABAC currently
                    ],
                    conditions={
                        "StringNotEquals": {
                            "aws:ResourceTag/ApplicationName": "Alarm Notifier",
                            "aws:ResourceTag/Environment": "Production",
                        }
                    },
                    effect=aws_iam.Effect.DENY,
                    resources=["*"],
                ),
                aws_iam.PolicyStatement(
                    actions=["ec2:DeleteTags", "tag:UntagResources"],
                    effect=aws_iam.Effect.DENY,
                    resources=["*"],
                ),
            ],
        )

        cdk_nag.NagSuppressions.add_resource_suppressions(
            construct=self.permissions_boundary,
            suppressions=[
                cdk_nag.NagPackSuppression(
                    applies_to=["Action::*", "Resource::*"],
                    id="AwsSolutions-IAM5",
                    reason="Permission boundaries are allowed to use wildcards",
                )
            ],
        )
