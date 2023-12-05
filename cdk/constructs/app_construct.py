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
)
from tbg_cdk import tbg_constructs


class AppConstruct(constructs.Construct):
    def __init__(
        self,
        scope: constructs.Construct,
        id: str,
        *,
        namer: tbg_cdk.IResourceNamer,
        sentry_env: str,
        sentry_dsn_secret_name: str,
        slack_alarm_notifier_oauth_token_secret_name: str,
        vpc: aws_ec2.IVpc,
    ):
        super().__init__(scope=scope, id=id)

        self._create_role_and_managed_policy(namer=namer)
        self._create_kms_key(namer=namer)
        self._create_dead_letter_queue(namer=namer)
        self._create_function_security_group(namer=namer, vpc=vpc)
        self._create_function_idempotency_table(namer=namer)
        self._create_function_data_table(namer=namer)
        self._create_function_parameters_and_secrets(
            namer=namer,
            sentry_env=sentry_env,
            sentry_dsn_secret_name=sentry_dsn_secret_name,
            slack_alarm_notifier_oauth_token_secret_name=slack_alarm_notifier_oauth_token_secret_name,
        )
        self._create_function(namer=namer, vpc=vpc)

    def _create_role_and_managed_policy(self, namer: tbg_cdk.IResourceNamer) -> None:
        self.alarm_notifier_role = aws_iam.Role(
            scope=self,
            id="Role",
            assumed_by=aws_iam.ServicePrincipal("lambda.amazonaws.com"),
            description="Alarm notifier execution role.",
            role_name=namer.get_name("Role"),
        )

        self.alarm_notifier_role.add_managed_policy(
            aws_iam.ManagedPolicy.from_aws_managed_policy_name(
                managed_policy_name="service-role/AWSLambdaVPCAccessExecutionRole"
            )
        )

        cdk_nag.NagSuppressions.add_resource_suppressions(
            construct=self.alarm_notifier_role,
            suppressions=[
                cdk_nag.NagPackSuppression(
                    id="AwsSolutions-IAM4",
                    reason="Use case allows for using the AWS Lambda VPC Access execution role managed policy.",
                    applies_to=[
                        "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
                    ],
                )
            ],
        )

        self.alarm_notifier_function_execution_managed_policy = aws_iam.ManagedPolicy(
            scope=self,
            id="GeneralManagedPolicy",
            description="General managed policy for the alarm notifier.",
            managed_policy_name=namer.get_name("FunctionExecutionManagedPolicy"),
            roles=[self.alarm_notifier_role],
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

    def _create_kms_key(self, namer: tbg_cdk.IResourceNamer) -> None:
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

        self.key_alias.grant_encrypt_decrypt(
            self.alarm_notifier_function_execution_managed_policy
        )

    def _create_dead_letter_queue(self, namer: tbg_cdk.IResourceNamer) -> None:
        self.dead_letter_queue = aws_sqs.Queue(
            scope=self,
            id="DeadLetterQueue",
            encryption=aws_sqs.QueueEncryption.KMS,
            encryption_master_key=self.key_alias,
            enforce_ssl=True,
            queue_name=namer.get_name("DeadLetterQueue"),
        )

    def _create_function_security_group(
        self, namer: tbg_cdk.IResourceNamer, vpc: aws_ec2.IVpc
    ) -> None:
        self.alarm_notification_function_security_group = aws_ec2.SecurityGroup(
            scope=self,
            id="AlarmNotificationFunctionSecurityGroup",
            allow_all_outbound=True,
            description="Alarm notification function security group.",
            security_group_name=namer.get_name(
                "AlarmNotificationFunctionSecurityGroup"
            ),
            vpc=vpc,
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
        sentry_dsn_secret_name: str,
        slack_alarm_notifier_oauth_token_secret_name: str,
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
            aws_secretsmanager.Secret.from_secret_name_v2(
                scope=self,
                id="AlarmNotificationSentryProjectSecret",
                secret_name=sentry_dsn_secret_name,
            )
        )

        self.alarm_notification_sentry_dsn_secret.grant_read(
            self.alarm_notifier_function_execution_managed_policy
        )

        self.alarm_notification_slack_oauth_secret = (
            aws_secretsmanager.Secret.from_secret_name_v2(
                scope=self,
                id="AlarmNotificationSlackOauthParameter",
                secret_name=slack_alarm_notifier_oauth_token_secret_name,
            )
        )

        self.alarm_notification_slack_oauth_secret.grant_read(
            self.alarm_notifier_function_execution_managed_policy
        )

    def _create_function(
        self, namer: tbg_cdk.IResourceNamer, vpc: aws_ec2.IVpc
    ) -> None:
        self.alarm_notifier = tbg_constructs.TopicQueueFunction(
            scope=self,
            id="AlarmNotifier",
            function_props=aws_lambda.FunctionProps(
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
                runtime=aws_lambda.Runtime.PYTHON_3_11,
                architecture=aws_lambda.Architecture.X86_64,
                description="Sends CloudWatch Alarm notification to Slack channels.",
                environment_encryption=self.key,
                environment={
                    "IDEMPOTENCY_TABLE_NAME_SSM_PARAMETER_NAME": self.alarm_notification_idempotency_table_name_parameter.parameter_name,
                    "ALARM_SLACK_CHANNELS_DYNAMODB_TABLE_SSM_PARAMETER_NAME": self.alarm_notification_slack_channels_table_name_parameter.parameter_name,
                    "SENTRY_DSN_SECRET_NAME": self.alarm_notification_sentry_dsn_secret.secret_name,
                    "SENTRY_ENV_SSM_PARAMETER_NAME": self.alarm_notification_sentry_env_parameter.parameter_name,
                    "SLACK_OAUTH_TOKEN_SECRET_NAME": self.alarm_notification_slack_oauth_secret.secret_name,
                },
                function_name=namer.get_name("Function"),
                insights_version=aws_lambda.LambdaInsightsVersion.VERSION_1_0_229_0,
                role=self.alarm_notifier_role.without_policy_updates(),
                security_groups=[self.alarm_notification_function_security_group],
                vpc=vpc,
                vpc_subnets=aws_ec2.SubnetSelection(
                    subnet_type=aws_ec2.SubnetType.PRIVATE_WITH_EGRESS
                ),
            ),
            queue_props=aws_sqs.QueueProps(
                dead_letter_queue=aws_sqs.DeadLetterQueue(
                    max_receive_count=5, queue=self.dead_letter_queue
                ),
                encryption=aws_sqs.QueueEncryption.KMS,
                encryption_master_key=self.key_alias,
                enforce_ssl=True,
                queue_name=namer.get_name("Queue"),
            ),
            topic_props=aws_sns.TopicProps(
                master_key=self.key_alias, topic_name=namer.get_name("Topic")
            ),
            log_group_props=aws_logs.LogGroupProps(
                encryption_key=self.key_alias,
                retention=aws_logs.RetentionDays.TWO_WEEKS,
            ),
            log_group_managed_policy_props=aws_iam.ManagedPolicyProps(
                description="Function log group managed policy.",
                managed_policy_name=namer.get_name("LogGroupManagedPolicy"),
            ),
            sqs_event_source_props=aws_lambda_event_sources.SqsEventSourceProps(
                report_batch_item_failures=True
            ),
        )

        cdk_nag.NagSuppressions.add_resource_suppressions(
            construct=self.alarm_notifier.fn,
            suppressions=[
                cdk_nag.NagPackSuppression(
                    id="AwsSolutions-L1",
                    reason="Use case allows for not using the latest runtime.",
                )
            ],
        )

        self.alarm_notifier.queue.grant_consume_messages(
            self.alarm_notifier_function_execution_managed_policy
        )
