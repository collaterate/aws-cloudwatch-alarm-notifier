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

        self.stack = cdk.stacks.application_stack.ApplicationStack(
            scope=self,
            id="AlarmNotifier",
            namer=namer.with_prefix("AlarmNotifier"),
            sentry_dsn_secret_name="/Sentry/AlarmNotifier/Dsn",
            sentry_env="dev",
            slack_alarm_notifier_oauth_token_secret_name="/Slack/AWSCloudWatchAlarmNotifier/BotUserOAuthToken",
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
                    not_actions=[
                        "ec2:CreateNetworkInterface",
                        "ec2:DescribeNetworkInterfaces",
                        "ec2:DeleteNetworkInterface",
                        "ec2:AssignPrivateIpAddresses",
                        "ec2:UnassignPrivateIpAddresses",
                        "secretsmanager:DescribeSecret",
                        "secretsmanager:GetSecretValue",
                        "ssm:GetParameter",
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
