import dataclasses
import enum
import logging
import os
import typing

import aws_lambda_powertools
import aws_lambda_powertools.utilities.batch
import aws_lambda_powertools.utilities.data_classes.sqs_event
import aws_lambda_powertools.utilities.idempotency
import aws_lambda_powertools.utilities.parser
import aws_lambda_powertools.utilities.parser.envelopes.event_bridge
import aws_lambda_powertools.utilities.typing
import pydantic
import pynamodb.attributes
import pynamodb.models
import pythonjsonlogger.jsonlogger
import sentry_sdk
import slack_sdk
import slack_sdk.errors
from aws_lambda_powertools.utilities import parameters
from aws_lambda_powertools.utilities.parser.models import EventBridgeModel
from aws_lambda_powertools.utilities.parser.types import Model
from sentry_sdk.integrations.aws_lambda import AwsLambdaIntegration
from sentry_sdk.integrations.logging import LoggingIntegration

sentry_sdk.init(
    dsn=parameters.get_secret(os.getenv("SENTRY_DSN_SECRET_ARN")),
    environment=parameters.get_parameter(os.getenv("SENTRY_ENV_SSM_PARAMETER_NAME")),
    integrations=[
        AwsLambdaIntegration(),
        LoggingIntegration(event_level=logging.CRITICAL),
    ],
)

processor = aws_lambda_powertools.utilities.batch.BatchProcessor(
    event_type=aws_lambda_powertools.utilities.batch.EventType.SQS
)

tracer = aws_lambda_powertools.Tracer()

dynamodb = aws_lambda_powertools.utilities.idempotency.DynamoDBPersistenceLayer(
    table_name=parameters.get_parameter(
        os.environ.get("IDEMPOTENCY_TABLE_NAME_SSM_PARAMETER_NAME")
    )
)

config = aws_lambda_powertools.utilities.idempotency.IdempotencyConfig(
    event_key_jmespath="id"
)

console_handler = logging.StreamHandler()
console_handler.setFormatter(
    pythonjsonlogger.jsonlogger.JsonFormatter(
        "%(asctime)s %(funcName)s %(levelname)s %(lineno)d %(message)s %(name)s %(pathname)s",
        rename_fields={
            "levelname": "level",
            "asctime": "timestamp",
            "lineno": "line",
            "funcName": "function",
            "pathname": "path",
        },
    )
)

logging.basicConfig(handlers=[console_handler], level=logging.DEBUG, force=True)

logger = logging.getLogger(__name__)


class CloudWatchAlarmEventDetailStateValue(str, enum.Enum):
    ALARM = "ALARM"
    OK = "OK"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class CloudWatchAlarmEventDetailState(pydantic.BaseModel):
    reason: str
    value: CloudWatchAlarmEventDetailStateValue


class CloudWatchAlarmEventDetail(pydantic.BaseModel):
    alarm_name: str = pydantic.Field(alias="alarmName")
    state: CloudWatchAlarmEventDetailState


class EventBridgeCloudWatchAlarmEvent(EventBridgeModel):
    detail: CloudWatchAlarmEventDetail


class AlarmSlackWebhookModel(pynamodb.models.Model):
    class Meta:
        table_name = parameters.get_parameter(
            os.getenv("ALARM_SLACK_CHANNELS_DYNAMODB_TABLE_SSM_PARAMETER_NAME")
        )

    alarm_arn = pynamodb.attributes.UnicodeAttribute(
        hash_key=True, attr_name="AlarmArn"
    )
    slack_channel_id = pynamodb.attributes.UnicodeAttribute(
        range_key=True, attr_name="SlackChannelId"
    )


class UnknownAlarmStateError(Exception):
    state: str

    def __str__(self) -> str:
        return f"unknown alarm state '{self.state}'"


def _build_slack_message(event: EventBridgeCloudWatchAlarmEvent):
    if event.detail.state.value == CloudWatchAlarmEventDetailStateValue.ALARM:
        logger.debug("detected alarm state")

        return [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"Alarm: {event.detail.alarm_name}",
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"{event.detail.state.reason}"},
                "accessory": {
                    "type": "image",
                    "image_url": "https://a.slack-edge.com/production-standard-emoji-assets/14.0/apple-large/1f6a8@2x.png",
                    "alt_text": "Siren",
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": "*Account*"},
                    {"type": "mrkdwn", "text": "*Region*"},
                    {"type": "mrkdwn", "text": f"`{event.account}`"},
                    {"type": "mrkdwn", "text": f"`{event.region}`"},
                    {"type": "mrkdwn", "text": "*ARNs*"},
                    {"type": "mrkdwn", "text": "*Timestamp*"},
                    {
                        "type": "mrkdwn",
                        "text": f"""`{", ".join(event.resources)}`""",
                    },
                    {"type": "mrkdwn", "text": f"`{event.time}`"},
                ],
            },
        ]
    elif event.detail.state.value == CloudWatchAlarmEventDetailStateValue.OK:
        logger.debug("detected ok state")

        return [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"Resolved: {event.detail.alarm_name}",
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"{event.detail.state.reason}"},
                "accessory": {
                    "type": "image",
                    "image_url": "https://a.slack-edge.com/production-standard-emoji-assets/14.0/apple-large/1f389@2x.png",
                    "alt_text": "Tada",
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": "*Account*"},
                    {"type": "mrkdwn", "text": "*Region*"},
                    {"type": "mrkdwn", "text": f"`{event.account}`"},
                    {"type": "mrkdwn", "text": f"`{event.region}`"},
                    {"type": "mrkdwn", "text": "*ARNs*"},
                    {"type": "mrkdwn", "text": "*Timestamp*"},
                    {
                        "type": "mrkdwn",
                        "text": f"""`{", ".join(event.resources)}`""",
                    },
                    {"type": "mrkdwn", "text": f"`{event.time}`"},
                ],
            },
        ]
    elif (
        event.detail.state.value
        == CloudWatchAlarmEventDetailStateValue.INSUFFICIENT_DATA
    ):
        logger.debug("detected insufficient data state")

        return [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"Insufficient data: {event.detail.alarm_name}",
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"{event.detail.state.reason}"},
                "accessory": {
                    "type": "image",
                    "image_url": "https://a.slack-edge.com/production-standard-emoji-assets/14.0/apple-large/2049-fe0f@2x.png",
                    "alt_text": "Tada",
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": "*Account*"},
                    {"type": "mrkdwn", "text": "*Region*"},
                    {"type": "mrkdwn", "text": f"`{event.account}`"},
                    {"type": "mrkdwn", "text": f"`{event.region}`"},
                    {"type": "mrkdwn", "text": "*ARNs*"},
                    {"type": "mrkdwn", "text": "*Timestamp*"},
                    {
                        "type": "mrkdwn",
                        "text": f"""`{", ".join(event.resources)}`""",
                    },
                    {"type": "mrkdwn", "text": f"`{event.time}`"},
                ],
            },
        ]
    else:
        logger.error("unknown alarm state", extra={"state": event.detail.state.value})

        raise UnknownAlarmStateError(event.detail.state.value)


@dataclasses.dataclass
class SendAlarmNotificationToSlackWebhookError(Exception):
    alarm_arn: str
    slack_channel_id: str
    response_content: str

    def __str__(self) -> str:
        return f"send alarm notification to slack channel failed [alarm_arn: {self.alarm_arn}, slack_channel_id: {self.slack_channel_id}, response_content: {self.response_content}]"


class SqsSnsEnvelope(aws_lambda_powertools.utilities.parser.envelopes.BaseEnvelope):
    def parse(
        self,
        data: typing.Optional[typing.Union[typing.Dict[str, typing.Any], typing.Any]],
        model: typing.Type[Model],
    ):
        sqs_record = (
            aws_lambda_powertools.utilities.parser.models.SqsRecordModel.parse_obj(data)
        )

        sns_record = self._parse(
            data=sqs_record.body,
            model=aws_lambda_powertools.utilities.parser.models.SnsNotificationModel,
        )

        return self._parse(data=sns_record.Message, model=model)


@tracer.capture_method
def record_handler(
    record: aws_lambda_powertools.utilities.data_classes.sqs_event.SQSRecord,
):
    event_handler(
        event=aws_lambda_powertools.utilities.parser.parse(
            envelope=SqsSnsEnvelope,
            event=dict(record),
            model=EventBridgeCloudWatchAlarmEvent,
        )
    )


@aws_lambda_powertools.utilities.idempotency.idempotent_function(
    data_keyword_argument="event", config=config, persistence_store=dynamodb
)
def event_handler(event: EventBridgeCloudWatchAlarmEvent):
    slack_client = slack_sdk.WebClient(
        token=parameters.get_secret(os.getenv("SLACK_OAUTH_TOKEN_SECRET_ARN"))
    )

    slack_message = _build_slack_message(event)

    logger.info("handling each event resource", extra={"resources": event.resources})

    for resource in event.resources:
        logger.info(
            "retrieving slack information for alarm", extra={"resource": resource}
        )

        models = list(AlarmSlackWebhookModel.query(resource))

        logger.info(
            "retrieved slack information for alarm",
            extra={"resource": resource, "models": models},
        )

        if len(models) == 0:
            logger.warning(
                "no slack channels defined for alarm",
                extra={"alarm_arn": resource},
            )

            continue

        for model in models:
            logger.info(
                "sending alarm notification to slack channel",
                extra={"slack_channel_id": model.slack_channel_id},
            )

            response = slack_client.chat_postMessage(
                blocks=slack_message, channel=model.slack_channel_id
            )

            try:
                response.validate()
            except slack_sdk.errors.SlackApiError:
                logger.exception(
                    "sending alarm notification to slack channel failed",
                    extra={
                        "slack_channel_id": model.slack_channel_id,
                        "message": slack_message,
                    },
                )

                raise
            else:
                logger.info(
                    "sent alarm notification to slack channel",
                    extra={"slack_channel_id": model.slack_channel_id},
                )


@tracer.capture_lambda_handler
def handler(event, context: aws_lambda_powertools.utilities.typing.LambdaContext):
    config.register_lambda_context(lambda_context=context)

    logger.debug("event", extra={"event": event})

    return aws_lambda_powertools.utilities.batch.process_partial_response(
        event=event,
        record_handler=record_handler,
        processor=processor,
        context=context,
    )
