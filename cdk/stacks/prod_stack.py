import aws_cdk
import constructs
import tbg_cdk
from aws_cdk import aws_ec2

import cdk.constructs.app_construct


class ProdStack(aws_cdk.Stack):
    def __init__(
        self,
        scope: constructs.Construct,
        id: str,
        *,
        namer: tbg_cdk.IResourceNamer,
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
            sentry_dsn_secret_name="Sentry/IntegrationApiDelivery/Dsn",
            sentry_env="prod",
            slack_alarm_notifier_oauth_token_secret_name="Slack/AWSCloudWatchAlarmNotifier/OAuthToken",
            vpc=vpc,
        )
