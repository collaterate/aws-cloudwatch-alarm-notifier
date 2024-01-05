import os
import typing

import aws_cdk
import cdk_nag
import constructs
import tbg_cdk
import tbg_cdk_nag
from aws_cdk import aws_ec2

import cdk.constructs.app_construct


class AlarmNotificationFunctionSecurityGroupFactory(typing.Protocol):
    def create(
        self,
        scope: constructs.Construct,
        id: str,
        *,
        namer: tbg_cdk.IResourceNamer,
        vpc: aws_ec2.IVpc,
    ) -> aws_ec2.ISecurityGroup:
        ...


class ApplicationStack(aws_cdk.Stack):
    def __init__(
        self,
        scope: constructs.Construct,
        id: str,
        *,
        alarm_notification_function_security_group_factory: AlarmNotificationFunctionSecurityGroupFactory,
        namer: tbg_cdk.IResourceNamer,
        sentry_dns_secret_complete_arn: str,
        sentry_env: str,
        slack_alarm_notifier_oauth_token_secret_complete_arn: str,
        vpc_id: str,
        **kwargs,
    ):
        super().__init__(scope=scope, id=id, **kwargs)

        self.app = cdk.constructs.app_construct.AppConstruct(
            scope=self,
            id="App",
            alarm_notification_function_security_group_factory=alarm_notification_function_security_group_factory,
            namer=namer.with_prefix("App"),
            sentry_dns_secret_complete_arn=sentry_dns_secret_complete_arn,
            sentry_env=sentry_env,
            slack_alarm_notifier_oauth_token_secret_complete_arn=slack_alarm_notifier_oauth_token_secret_complete_arn,
            vpc_id=vpc_id,
        )

        aws_cdk.Aspects.of(self).add(
            tbg_cdk.tbg_aspects.SetRemovalPolicy(policy=aws_cdk.RemovalPolicy.DESTROY)
        )

        aws_cdk.Aspects.of(self).add(cdk_nag.AwsSolutionsChecks(verbose=True))
        aws_cdk.Aspects.of(self).add(tbg_cdk_nag.TbgSolutionsChecks(verbose=True))

        aws_cdk.Tags.of(self).add("ApplicationName", "Alarm Notifier")
        aws_cdk.Tags.of(self).add("Region", self.region)

        aws_cdk.Tags.of(self).add("ApplicationVersion", os.getenv("VERSION"))
