import json

import aws_cdk
import cdk_nag
import constructs
import tbg_cdk
from aws_cdk import aws_iam

import cdk.stacks.application_stack


class DevStage(aws_cdk.Stage):
    def __init__(self, scope: constructs.Construct, id: str, **kwargs):
        super().__init__(scope=scope, id=id, **kwargs)

        namer = tbg_cdk.ResourceNamer(["Dev", "Prv", "UE1"])

        with open("./slack-api-ips.json") as f:
            slack_api_ips = json.load(f)

        with open("./sentry-ingest-ips.json") as f:
            sentry_ingest_ips = json.load(f)

        self.stack = cdk.stacks.application_stack.ApplicationStack(
            scope=self,
            id="AlarmNotifier",
            namer=namer.with_prefix("AlarmNotifier"),
            sentry_dns_secret_complete_arn="arn:aws:secretsmanager:us-east-1:800572224722:secret:/Sentry/AlarmNotifier/Dsn-7qkInJ",
            sentry_env="dev",
            sentry_ingest_ips=sentry_ingest_ips,
            slack_alarm_notifier_oauth_token_secret_complete_arn="arn:aws:secretsmanager:us-east-1:800572224722:secret:/Slack/AWSCloudWatchAlarmNotifier/BotUserOAuthToken-529oMU",  # TODO create a unique token for this bot
            slack_api_ips=slack_api_ips,
            stack_name=namer.get_name("AlarmNotifier"),
        )

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
                        "arn:aws:kms:us-east-1:800572224722:key/0dd0a066-0a63-4bce-8245-ccbb28cccc60",
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

        aws_iam.PermissionsBoundary.of(self.stack).apply(self.permissions_boundary)

        aws_cdk.Tags.of(self).add("Environment", "Development")
