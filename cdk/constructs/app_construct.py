import typing

import aws_cdk
import cdk_nag
import constructs
import tbg_cdk
from aws_cdk import (
    aws_iam,
    aws_kms,
    aws_sqs,
    aws_ec2,
    aws_dynamodb,
    aws_ssm,
    aws_lambda,
    aws_sns,
    aws_logs,
    aws_lambda_event_sources,
    aws_secretsmanager,
    aws_sns_subscriptions,
)


class AppConstruct(constructs.Construct):
    """
    The AWS CloudWatch Alarm Notifier

    Creates an SNS Topic that can be used with the `AlarmActions` of a CloudWatch Alarm to send alarm transition messages to Slack.

    Developers should use the `tbg-cdk.RegisterAlarmSlackChannel` construct to configure what Slack channels are notified of alarm transitions.
    """

    def __init__(
        self,
        scope: constructs.Construct,
        id: str,
        *,
        namer: tbg_cdk.IResourceNamer,
        sentry_env: str,
        sentry_dns_secret_complete_arn: str,
        sentry_ingest_ips: typing.Sequence[str],
        slack_alarm_notifier_oauth_token_secret_complete_arn: str,
        slack_api_ips: typing.Sequence[str],
        vpc: aws_ec2.IVpc,
    ):
        super().__init__(scope=scope, id=id)

        self._create_role_and_managed_policy(namer=namer)
        self._create_kms_key(namer=namer)
        self._create_topic(namer=namer)
        self._create_dead_letter_queue(namer=namer)
        self._create_queue(namer=namer)
        self._create_function_security_group(
            namer=namer,
            sentry_ingest_ips=sentry_ingest_ips,
            slack_api_ips=slack_api_ips,
            vpc=vpc,
        )
        self._create_function_idempotency_table(namer=namer)
        self._create_function_data_table(namer=namer)
        self._create_function_parameters_and_secrets(
            namer=namer,
            sentry_env=sentry_env,
            sentry_dns_secret_complete_arn=sentry_dns_secret_complete_arn,
            slack_alarm_notifier_oauth_token_secret_complete_arn=slack_alarm_notifier_oauth_token_secret_complete_arn,
        )
        self._create_function_log_group(namer=namer)
        self._create_function(namer=namer, vpc=vpc)

    def _create_role_and_managed_policy(self, namer: tbg_cdk.IResourceNamer) -> None:
        """Create the role and managed policy for the Alarm Notifier function"""
        self.alarm_notifier_role = aws_iam.Role(
            scope=self,
            id="Role",
            assumed_by=aws_iam.ServicePrincipal("lambda.amazonaws.com"),
            description="Alarm notifier execution role.",
            role_name=namer.get_name("Role"),
        )

        self.alarm_notifier_function_execution_managed_policy = aws_iam.ManagedPolicy(
            scope=self,
            id="GeneralManagedPolicy",
            description="General managed policy for the alarm notifier.",
            managed_policy_name=namer.get_name("FunctionExecutionManagedPolicy"),
            roles=[self.alarm_notifier_role],
        )

    def _create_kms_key(self, namer: tbg_cdk.IResourceNamer) -> None:
        """Create a KMS key for the Alarm Notifier application."""
        self.key = aws_kms.Key(
            scope=self,
            id="Key",
            description="Alarm notifier key.",
            enable_key_rotation=True,
        )

        self.key_alias = self.key.add_alias(
            alias_name=namer.get_name("AlarmNotifierKey")
        )

        self.key_alias.grant_encrypt_decrypt(
            aws_iam.ServicePrincipal(f"logs.{aws_cdk.Aws.REGION}.amazonaws.com")
        )

        # Allow CloudWatch to use the encryption key, which is required for alarms to publish to SNS topics
        self.key_alias.grant_encrypt_decrypt(
            aws_iam.ServicePrincipal(service="cloudwatch.amazonaws.com")
        )

        self.key.grant_encrypt_decrypt(
            self.alarm_notifier_function_execution_managed_policy
        )

        cdk_nag.NagSuppressions.add_resource_suppressions(
            construct=self.alarm_notifier_function_execution_managed_policy,
            suppressions=[
                cdk_nag.NagPackSuppression(
                    id="AwsSolutions-IAM5",
                    reason="Use case allows for wildcard actions",
                    applies_to=[
                        "Action::kms:GenerateDataKey*",
                        "Action::kms:ReEncrypt*",
                    ],
                )
            ],
        )

    def _create_topic(self, namer: tbg_cdk.IResourceNamer) -> None:
        """Create an SNS topic for the Alarm Notifier application."""
        self.alarm_notifier_topic = aws_sns.Topic(
            scope=self,
            id="AlarmNotifierTopic",
            master_key=self.key_alias,
            topic_name=namer.get_name("Topic"),
        )

        # Allow CloudWatch to publish to the SNS topic
        self.alarm_notifier_topic.grant_publish(
            grantee=aws_iam.ServicePrincipal(service="cloudwatch.amazonaws.com")
        )

    def _create_dead_letter_queue(self, namer: tbg_cdk.IResourceNamer) -> None:
        self.alarm_notifier_dead_letter_queue = aws_sqs.Queue(
            scope=self,
            id="DeadLetterQueue",
            encryption=aws_sqs.QueueEncryption.KMS,
            encryption_master_key=self.key_alias,
            enforce_ssl=True,
            queue_name=namer.get_name("DeadLetterQueue"),
        )

    def _create_queue(self, namer: tbg_cdk.IResourceNamer) -> None:
        self.alarm_notifier_queue = aws_sqs.Queue(
            scope=self,
            id="AlarmNotifierQueue",
            dead_letter_queue=aws_sqs.DeadLetterQueue(
                max_receive_count=5, queue=self.alarm_notifier_dead_letter_queue
            ),
            encryption=aws_sqs.QueueEncryption.KMS,
            encryption_master_key=self.key_alias,
            enforce_ssl=True,
            queue_name=namer.get_name("Queue"),
        )

        self.alarm_notifier_topic.add_subscription(
            aws_sns_subscriptions.SqsSubscription(
                dead_letter_queue=self.alarm_notifier_dead_letter_queue,
                queue=self.alarm_notifier_queue,
            )
        )

    def _create_function_security_group(
        self,
        namer: tbg_cdk.IResourceNamer,
        sentry_ingest_ips: typing.Sequence[str],
        slack_api_ips: typing.Sequence[str],
        vpc: aws_ec2.IVpc,
    ) -> None:
        self.alarm_notification_function_security_group = aws_ec2.SecurityGroup(
            scope=self,
            id="AlarmNotificationFunctionSecurityGroup",
            allow_all_outbound=False,
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
                security_group_id="sg-0a605696d8cbad464"
            ),
            port_range=aws_ec2.Port.tcp(port=443),
            description="Allow connections to the VPC endpoints.",
        )

        self.alarm_notification_function_security_group.connections.allow_to(
            other=aws_ec2.Peer.prefix_list(prefix_list_id="pl-02cd2c6b"),
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

    def _create_function_idempotency_table(self, namer: tbg_cdk.IResourceNamer) -> None:
        self.alarm_notification_idempotency_table = aws_dynamodb.Table(
            scope=self,
            id="AlarmNotificationIdempotencyTable",
            table_name=namer.get_name("AlarmNotificationIdempotencyTable"),
            partition_key=aws_dynamodb.Attribute(
                name="id", type=aws_dynamodb.AttributeType.STRING
            ),
            billing_mode=aws_dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=aws_dynamodb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=self.key_alias,
            time_to_live_attribute="expiration",
            point_in_time_recovery=True,
        )

        self.alarm_notification_idempotency_table.grant_read_write_data(
            self.alarm_notifier_function_execution_managed_policy
        )

    def _create_function_data_table(self, namer: tbg_cdk.IResourceNamer) -> None:
        self.alarm_notification_slack_channels_table = aws_dynamodb.Table(
            scope=self,
            id="AlarmToSlackChannelsTable",
            table_name=namer.get_name("AlarmToSlackChannelsTable"),
            partition_key=aws_dynamodb.Attribute(
                name="AlarmArn", type=aws_dynamodb.AttributeType.STRING
            ),
            sort_key=aws_dynamodb.Attribute(
                name="SlackChannelId", type=aws_dynamodb.AttributeType.STRING
            ),
            billing_mode=aws_dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=aws_dynamodb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=self.key_alias,
            point_in_time_recovery=True,
        )

        self.alarm_notification_slack_channels_table.grant_read_write_data(
            self.alarm_notifier_function_execution_managed_policy
        )

    def _create_function_parameters_and_secrets(
        self,
        namer: tbg_cdk.IResourceNamer,
        sentry_env: str,
        sentry_dns_secret_complete_arn: str,
        slack_alarm_notifier_oauth_token_secret_complete_arn: str,
    ) -> None:
        self.alarm_notification_idempotency_table_name_parameter = aws_ssm.StringParameter(
            scope=self,
            id="AlarmNotificationIdempotencyTableNameParameter",
            description="Name of the alarm notification idempotency DynamoDB table.",
            parameter_name=namer.get_parameter_name(
                "AlarmNotificationIdempotencyTableName"
            ),
            string_value=self.alarm_notification_idempotency_table.table_name,
        )

        self.alarm_notification_idempotency_table_name_parameter.grant_read(
            self.alarm_notifier_function_execution_managed_policy
        )

        self.alarm_notification_slack_channels_table_name_parameter = (
            aws_ssm.StringParameter(
                scope=self,
                id="AlarmToSlackChannelsTableNameParameter",
                description="Name of the alarm to slack channel ids DynamoDB table.",
                parameter_name=namer.get_parameter_name(
                    "AlarmToSlackChannelsTableNameSsmParameter"
                ),
                string_value=self.alarm_notification_slack_channels_table.table_name,
            )
        )

        self.alarm_notification_slack_channels_table_name_parameter.grant_read(
            self.alarm_notifier_function_execution_managed_policy
        )

        self.alarm_notification_sentry_env_parameter = aws_ssm.StringParameter(
            scope=self,
            id="AlarmNotificationSentryEnvParameter",
            description="Environment of the Sentry project for the alarm notifier Lambda function.",
            parameter_name=namer.get_parameter_name(
                "AlarmNotificationSentryEnvParameter"
            ),
            string_value=sentry_env,
        )

        self.alarm_notification_sentry_env_parameter.grant_read(
            self.alarm_notifier_function_execution_managed_policy
        )

        self.alarm_notification_sentry_dsn_secret = (
            aws_secretsmanager.Secret.from_secret_complete_arn(
                scope=self,
                id="AlarmNotificationSentryProjectSecret",
                secret_complete_arn=sentry_dns_secret_complete_arn,
            )
        )

        self.alarm_notification_sentry_dsn_secret.grant_read(
            self.alarm_notifier_function_execution_managed_policy
        )

        self.alarm_notification_slack_oauth_secret = aws_secretsmanager.Secret.from_secret_complete_arn(
            scope=self,
            id="AlarmNotificationSlackOauthParameter",
            secret_complete_arn=slack_alarm_notifier_oauth_token_secret_complete_arn,
        )

        self.alarm_notification_slack_oauth_secret.grant_read(
            self.alarm_notifier_function_execution_managed_policy
        )

    def _create_function_log_group(self, namer: tbg_cdk.IResourceNamer) -> None:
        self.alarm_notifier_function_log_group = aws_logs.LogGroup(
            scope=self,
            id="AlarmNotifierLogGroup",
            log_group_name=f"/aws/lambda/{namer.get_name('Function')}",
            encryption_key=self.key_alias,
            retention=aws_logs.RetentionDays.TWO_WEEKS,
        )

    def _create_function(
        self, namer: tbg_cdk.IResourceNamer, vpc: aws_ec2.IVpc
    ) -> None:
        self.alarm_notifier_function_log_group.grant_write(
            self.alarm_notifier_function_execution_managed_policy
        )

        self.alarm_notifier_queue.grant_consume_messages(
            self.alarm_notifier_function_execution_managed_policy
        )

        self.alarm_notifier_function_execution_managed_policy.add_statements(
            aws_iam.PolicyStatement(
                actions=[
                    "ec2:CreateNetworkInterface",
                    "ec2:DescribeNetworkInterfaces",
                    "ec2:DeleteNetworkInterface",
                    "ec2:AssignPrivateIpAddresses",
                    "ec2:UnassignPrivateIpAddresses",
                ],
                resources=["*"],
            )
        )

        cdk_nag.NagSuppressions.add_resource_suppressions(
            construct=self.alarm_notifier_function_execution_managed_policy,
            suppressions=[
                cdk_nag.NagPackSuppression(
                    id="AwsSolutions-IAM5",
                    reason="Wildcard resource is required for Lambda VPC networking.",
                )
            ],
        )

        self.alarm_notifier_function = aws_lambda.Function(
            scope=self,
            id="Function",
            code=aws_lambda.Code.from_docker_build(
                path=".",
                build_args={
                    "CODEARTIFACT_AUTHORIZATION_TOKEN": self.node.try_get_context(
                        "codeartifact_authorization_token"
                    ),
                    "POETRY_INSTALL_ARGS": "--only=handler",
                },
                file="Dockerfile.alarm_notifier",
            ),
            handler="alarm_notifier.lambda_handler.handler",
            runtime=aws_lambda.Runtime.PYTHON_3_12,
            architecture=aws_lambda.Architecture.X86_64,
            description="Sends CloudWatch Alarm notification to Slack channels.",
            environment_encryption=self.key,
            environment={
                "IDEMPOTENCY_TABLE_NAME_SSM_PARAMETER_NAME": self.alarm_notification_idempotency_table_name_parameter.parameter_name,
                "ALARM_SLACK_CHANNELS_DYNAMODB_TABLE_SSM_PARAMETER_NAME": self.alarm_notification_slack_channels_table_name_parameter.parameter_name,
                "SENTRY_DSN_SECRET_ARN": self.alarm_notification_sentry_dsn_secret.secret_full_arn,
                "SENTRY_ENV_SSM_PARAMETER_NAME": self.alarm_notification_sentry_env_parameter.parameter_name,
                "SLACK_OAUTH_TOKEN_SECRET_ARN": self.alarm_notification_slack_oauth_secret.secret_full_arn,
            },
            function_name=namer.get_name("Function"),
            log_format=aws_lambda.LogFormat.JSON.value,
            log_group=self.alarm_notifier_function_log_group,
            system_log_level=aws_lambda.SystemLogLevel.DEBUG.value,
            application_log_level=aws_lambda.ApplicationLogLevel.DEBUG.value,
            insights_version=aws_lambda.LambdaInsightsVersion.VERSION_1_0_229_0,
            role=self.alarm_notifier_role.without_policy_updates(),
            security_groups=[self.alarm_notification_function_security_group],
            timeout=aws_cdk.Duration.seconds(30),
            vpc=vpc,
            vpc_subnets=aws_ec2.SubnetSelection(
                subnet_type=aws_ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
        )

        self.alarm_notifier_function.node.add_dependency(
            self.alarm_notifier_function_execution_managed_policy
        )

        self.alarm_notifier_function.add_event_source(
            source=aws_lambda_event_sources.SqsEventSource(
                queue=self.alarm_notifier_queue, report_batch_item_failures=True
            )
        )
