import os
import typing

import aws_cdk
import cdk_nag
import constructs
import tbg_cdk
import tbg_cdk_nag
from aws_cdk import aws_ec2

import cdk.constructs.app_construct


class ApplicationStack(aws_cdk.Stack):
    def __init__(
        self,
        scope: constructs.Construct,
        id: str,
        *,
        namer: tbg_cdk.IResourceNamer,
        sentry_dns_secret_complete_arn: str,
        sentry_env: str,
        slack_api_ips: typing.Sequence[str],
        slack_alarm_notifier_oauth_token_secret_complete_arn: str,
        **kwargs
    ):
        super().__init__(scope=scope, id=id, **kwargs)

        vpc = aws_ec2.Vpc.from_lookup(
            scope=self, id="Vpc", tags={"AccountResourceId": "Vpc"}
        )

        self.app = cdk.constructs.app_construct.AppConstruct(
            scope=self,
            id="App",
            namer=namer.with_prefix("App"),
            sentry_dns_secret_complete_arn=sentry_dns_secret_complete_arn,
            sentry_env=sentry_env,
            slack_api_ips=slack_api_ips,
            slack_alarm_notifier_oauth_token_secret_complete_arn=slack_alarm_notifier_oauth_token_secret_complete_arn,
            vpc=vpc,
        )

        aws_cdk.Aspects.of(self).add(
            tbg_cdk.tbg_aspects.SetRemovalPolicy(policy=aws_cdk.RemovalPolicy.DESTROY)
        )

        aws_cdk.Aspects.of(self).add(cdk_nag.AwsSolutionsChecks(verbose=True))
        aws_cdk.Aspects.of(self).add(tbg_cdk_nag.TbgSolutionsChecks(verbose=True))

        aws_cdk.Tags.of(self).add("ApplicationName", "Alarm Notifier")
        aws_cdk.Tags.of(self).add("Region", self.region)

        aws_cdk.Tags.of(self).add("ApplicationVersion", os.getenv("VERSION"))
