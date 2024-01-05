import typing

import pydantic


class AwsConfig(pydantic.BaseModel):
    dynamodb_prefix_list_id: str = pydantic.Field(alias="dynamodb-prefix-list-id")
    secrets_manager_key_arn: str = pydantic.Field(alias="secrets-manager-key-arn")
    sentry_dsn_secret_arn: str = pydantic.Field(alias="sentry-dns-secret-arn")
    slack_alarm_notifier_oauth_token_secret_arn: str = pydantic.Field(
        alias="slack-alarm-notifier-oauth-token-secret-arn"
    )
    vpc_id: str = pydantic.Field(alias="vpc-id")
    vpc_endpoints_security_group_id: typing.Optional[str] = pydantic.Field(
        alias="vpc-endpoints-security-group-id"
    )
