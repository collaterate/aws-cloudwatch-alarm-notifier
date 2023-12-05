import os

import aws_cdk
import cdk_nag
import constructs
import tbg_cdk
import tbg_cdk_nag
from aws_cdk import aws_lambda

import cdk.stacks.application_stack


class DevStage(aws_cdk.Stage):
    def __init__(self, scope: constructs.Construct, id: str, **kwargs):
        super().__init__(scope=scope, id=id, **kwargs)

        namer = tbg_cdk.ResourceNamer(["Dev", "Prv", "UE1"])

        alarm_notifier_code = aws_lambda.Code.from_docker_build(
            path=".",
            build_args={
                "CODEARTIFACT_AUTHORIZATION_TOKEN": self.node.try_get_context(
                    "codeartifact_authorization_token"
                ),
                "POETRY_INSTALL_ARGS": "--only=handler",
            },
            file="Dockerfile.alarm_notifier",
        )

        self.stack = cdk.stacks.application_stack.ApplicationStack(
            scope=self,
            id="AlarmNotifier",
            alarm_notifier_code=alarm_notifier_code,
            namer=namer.with_prefix("AlarmNotifier"),
            sentry_dsn_secret_name="/Sentry/AlarmNotifier/Dsn",
            sentry_env="dev",
            slack_alarm_notifier_oauth_token_secret_name="/Slack/AWSCloudWatchAlarmNotifier/BotUserOAuthToken",
            stack_name=namer.get_name("AlarmNotifier"),
        )

        aws_cdk.Aspects.of(self).add(
            tbg_cdk.tbg_aspects.SetRemovalPolicy(policy=aws_cdk.RemovalPolicy.DESTROY)
        )

        aws_cdk.Aspects.of(self).add(cdk_nag.AwsSolutionsChecks(verbose=True))
        aws_cdk.Aspects.of(self).add(tbg_cdk_nag.TbgSolutionsChecks(verbose=True))

        aws_cdk.Tags.of(self).add("ApplicationName", "Alarm Notifier")
        aws_cdk.Tags.of(self).add("Environment", "Development")
        aws_cdk.Tags.of(self).add("Region", "us-east-1")

        aws_cdk.Tags.of(self).add("ApplicationVersion", os.getenv("VERSION"))
