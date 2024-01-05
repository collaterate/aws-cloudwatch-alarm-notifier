import dataclasses
import json
import typing

import aws_cdk
import cdk_nag
import constructs
import tbg_cdk
from aws_cdk import aws_iam, aws_ec2

import cdk.stacks.application_stack
from cdk.aws_config import AwsConfig


@dataclasses.dataclass
class DevAlarmNotificationFunctionSecurityGroupFactory:
    dynamodb_prefix_list_id: str
    sentry_ingest_ips: typing.Sequence[str]
    slack_api_ips: typing.Sequence[str]
    vpc_endpoints_security_group_id: str

    def create(
        self,
        scope: constructs.Construct,
        id: str,
        *,
        namer: tbg_cdk.IResourceNamer,
        vpc: aws_ec2.IVpc,
    ) -> aws_ec2.ISecurityGroup:
        alarm_notification_function_security_group = aws_ec2.SecurityGroup(
            scope=scope,
            id=id,
            description="Alarm notification function security group.",
            security_group_name=namer.get_name(
                "AlarmNotificationFunctionSecurityGroup"
            ),
            vpc=vpc,
        )

        aws_cdk.Tags.of(alarm_notification_function_security_group).add(
            key="Name", value=namer.get_name("AlarmNotificationFunctionSecurityGroup")
        )

        slack_api_ips_prefix_list = aws_ec2.PrefixList(
            scope=scope,
            id="SlackApiIpsPrefixList",
            address_family=aws_ec2.AddressFamily.IP_V4,
            entries=[
                aws_ec2.CfnPrefixList.EntryProperty(cidr=f"{ip}/32")
                for ip in self.slack_api_ips
            ],
            prefix_list_name=namer.get_name("SlackApiIpsPrefixList"),
        )

        alarm_notification_function_security_group.connections.allow_to(
            other=aws_ec2.Peer.prefix_list(
                prefix_list_id=slack_api_ips_prefix_list.prefix_list_id
            ),
            port_range=aws_ec2.Port.tcp(port=443),
            description="Allow connections to the Slack API servers.",
        )

        alarm_notification_function_security_group.connections.allow_to(
            other=aws_ec2.Peer.security_group_id(
                security_group_id=self.vpc_endpoints_security_group_id
            ),
            port_range=aws_ec2.Port.tcp(port=443),
            description="Allow connections to the VPC endpoints.",
        )

        alarm_notification_function_security_group.connections.allow_to(
            other=aws_ec2.Peer.prefix_list(prefix_list_id=self.dynamodb_prefix_list_id),
            port_range=aws_ec2.Port.tcp(443),
            description="Allow connections to the DynamoDB endpoint.",
        )

        sentry_ingest_ips_prefix_list = aws_ec2.PrefixList(
            scope=scope,
            id="SentryIngestIpsPrefixList",
            address_family=aws_ec2.AddressFamily.IP_V4,
            entries=[
                aws_ec2.CfnPrefixList.EntryProperty(cidr=f"{ip}/32")
                for ip in self.sentry_ingest_ips
            ],
            prefix_list_name=namer.get_name("SentryIngestIpsPrefixList"),
        )

        alarm_notification_function_security_group.connections.allow_to(
            other=aws_ec2.Peer.prefix_list(
                prefix_list_id=sentry_ingest_ips_prefix_list.prefix_list_id
            ),
            port_range=aws_ec2.Port.tcp(443),
            description="Allow connection to Sentry.",
        )

        return alarm_notification_function_security_group


class DevStage(aws_cdk.Stage):
    def __init__(self, scope: constructs.Construct, id: str, **kwargs):
        super().__init__(scope=scope, id=id, **kwargs)

        namer = tbg_cdk.ResourceNamer(["Dev", "Prv", "UE1"])

        with open("./slack-api-ips.json") as f:
            slack_api_ips = json.load(f)

        with open("./sentry-ingest-ips.json") as f:
            sentry_ingest_ips = json.load(f)

        with open("./aws-config-dev.json") as f:
            aws_config = AwsConfig.model_validate_json(f.read())

        self._create_stack(
            dynamodb_prefix_list_id=aws_config.dynamodb_prefix_list_id,
            namer=namer,
            sentry_dsn_secret_arn=aws_config.sentry_dsn_secret_arn,
            sentry_ingest_ips=sentry_ingest_ips,
            slack_alarm_notifier_oauth_token_secret_complete_arn=aws_config.slack_alarm_notifier_oauth_token_secret_arn,
            slack_api_ips=slack_api_ips,
            vpc_id=aws_config.vpc_id,
            vpc_endpoints_security_group_id=aws_config.vpc_endpoints_security_group_id,
        )

        self._create_permissions_boundary_managed_policy(
            namer=namer, secrets_manager_key_arn=aws_config.secrets_manager_key_arn
        )

        aws_iam.PermissionsBoundary.of(self.stack).apply(self.permissions_boundary)

        aws_cdk.Tags.of(self).add("Environment", "Development")

    def _create_stack(
        self,
        dynamodb_prefix_list_id: str,
        namer: tbg_cdk.IResourceNamer,
        sentry_dsn_secret_arn: str,
        sentry_ingest_ips: typing.Sequence[str],
        slack_alarm_notifier_oauth_token_secret_complete_arn: str,
        slack_api_ips: typing.Sequence[str],
        vpc_id: str,
        vpc_endpoints_security_group_id: str,
    ) -> None:
        self.stack = cdk.stacks.application_stack.ApplicationStack(
            scope=self,
            id="AlarmNotifier",
            alarm_notification_function_security_group_factory=DevAlarmNotificationFunctionSecurityGroupFactory(
                dynamodb_prefix_list_id=dynamodb_prefix_list_id,
                sentry_ingest_ips=sentry_ingest_ips,
                slack_api_ips=slack_api_ips,
                vpc_endpoints_security_group_id=vpc_endpoints_security_group_id,
            ),
            namer=namer.with_prefix("AlarmNotifier"),
            sentry_dns_secret_complete_arn=sentry_dsn_secret_arn,
            sentry_env="dev",
            slack_alarm_notifier_oauth_token_secret_complete_arn=slack_alarm_notifier_oauth_token_secret_complete_arn,  # TODO create a unique token for this bot
            stack_name=namer.get_name("AlarmNotifier"),
            vpc_id=vpc_id,
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
                    not_resources=[
                        secrets_manager_key_arn,
                        self.stack.app.key.key_arn,
                    ],
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
                            "aws:ResourceTag/Environment": "Development",
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

    def _create_function_security_group(
        self,
        dynamodb_prefix_list_id: str,
        namer: tbg_cdk.IResourceNamer,
        sentry_ingest_ips: typing.Sequence[str],
        slack_api_ips: typing.Sequence[str],
        vpc: aws_ec2.IVpc,
        vpc_endpoints_security_group_id: str,
    ) -> None:
        self.alarm_notification_function_security_group = aws_ec2.SecurityGroup(
            scope=self,
            id="AlarmNotificationFunctionSecurityGroup",
            description="Alarm notification function security group.",
            security_group_name=namer.get_name(
                "AlarmNotificationFunctionSecurityGroup"
            ),
            vpc=vpc,
        )

        aws_cdk.Tags.of(self.alarm_notification_function_security_group).add(
            key="Name", value=namer.get_name("AlarmNotificationFunctionSecurityGroup")
        )

        self.slack_api_ips_prefix_list = aws_ec2.PrefixList(
            scope=self,
            id="SlackApiIpsPrefixList",
            address_family=aws_ec2.AddressFamily.IP_V4,
            entries=[
                aws_ec2.CfnPrefixList.EntryProperty(cidr=f"{ip}/32")
                for ip in slack_api_ips
            ],
            prefix_list_name=namer.get_name("SlackApiIpsPrefixList"),
        )

        self.alarm_notification_function_security_group.connections.allow_to(
            other=aws_ec2.Peer.prefix_list(
                prefix_list_id=self.slack_api_ips_prefix_list.prefix_list_id
            ),
            port_range=aws_ec2.Port.tcp(port=443),
            description="Allow connections to the Slack API servers.",
        )

        self.alarm_notification_function_security_group.connections.allow_to(
            other=aws_ec2.Peer.security_group_id(
                security_group_id=vpc_endpoints_security_group_id
            ),
            port_range=aws_ec2.Port.tcp(port=443),
            description="Allow connections to the VPC endpoints.",
        )

        self.alarm_notification_function_security_group.connections.allow_to(
            other=aws_ec2.Peer.prefix_list(prefix_list_id=dynamodb_prefix_list_id),
            port_range=aws_ec2.Port.tcp(443),
            description="Allow connections to the DynamoDB endpoint.",
        )

        self.sentry_ingest_ips_prefix_list = aws_ec2.PrefixList(
            scope=self,
            id="SentryIngestIpsPrefixList",
            address_family=aws_ec2.AddressFamily.IP_V4,
            entries=[
                aws_ec2.CfnPrefixList.EntryProperty(cidr=f"{ip}/32")
                for ip in sentry_ingest_ips
            ],
            prefix_list_name=namer.get_name("SentryIngestIpsPrefixList"),
        )
