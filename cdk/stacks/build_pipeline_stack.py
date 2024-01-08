import typing

import aws_cdk
import cdk_nag
import constructs
import tbg_cdk
from aws_cdk import pipelines, aws_iam, aws_codestarconnections

import cdk.stages.dev_stage
import cdk.stages.prod_stage
from cdk.aws_config import AwsConfig


class BuildProdPipelineStack(aws_cdk.Stack):
    def __init__(
        self,
        scope: constructs.Construct,
        id: str,
        *,
        aws_config: AwsConfig,
        namer: tbg_cdk.IResourceNamer,
        sentry_ingest_ips: typing.Sequence[str],
        slack_api_ips: typing.Sequence[str],
        **kwargs
    ):
        super().__init__(scope=scope, id=id, **kwargs)

        self.github_connection = aws_codestarconnections.CfnConnection(
            scope=self,
            id="AlarmNotifierGitHubConnection",
            connection_name="AlarmNotifierGitHubConnection",
            provider_type="GitHub",
        )

        self.pipeline = pipelines.CodePipeline(
            scope=self,
            id="ProdPipeline",
            pipeline_name=namer.get_name("AwsAlarmNotifierProdPipeline"),
            synth=pipelines.ShellStep(
                id="Synth",
                commands=[
                    "export ASDF_DIR=~/.asdf",
                    "git clone https://github.com/asdf-vm/asdf.git ~/.asdf --branch v0.13.1",
                    ". $ASDF_DIR/asdf.sh",
                    "asdf plugin add nodejs",
                    "asdf plugin add poetry",
                    "asdf plugin add python",
                    "asdf plugin add awscli",
                    "asdf install",
                    "npm i",
                    "poetry config http-basic.tbg aws $(aws codeartifact get-authorization-token --duration-seconds 3600 --domain tbg --domain-owner 538493872512 --query authorizationToken --output text)",
                    "poetry install --no-root --without=dev",
                    """npx cdk --context codeartifact_authorization_token=`aws codeartifact get-authorization-token --duration-seconds 3600 --domain tbg --domain-owner 538493872512 --query authorizationToken --output text` --app "VERSION=`poetry version --short` poetry run python -m cdk.prod" synth ProdAlarmNotifierPipeline""",
                ],
                input=pipelines.CodePipelineSource.connection(
                    repo_string="collaterate/aws-cloudwatch-alarm-notifier",
                    branch="main",
                    connection_arn=self.github_connection.attr_connection_arn,
                    action_name=namer.get_name("GitHub"),
                ),
            ),
            synth_code_build_defaults=pipelines.CodeBuildOptions(
                role_policy=[
                    aws_iam.PolicyStatement(
                        actions=[
                            "codeartifact:GetAuthorizationToken",
                            "codeartifact:GetRepositoryEndpoint",
                            "codeartifact:ReadFromRepository",
                        ],
                        effect=aws_iam.Effect.ALLOW,
                        resources=[
                            self.node.try_get_context("tbg-codeartifact-domain-arn")
                        ],
                    ),
                    aws_iam.PolicyStatement(
                        actions=[
                            "codeartifact:GetRepositoryEndpoint",
                            "codeartifact:ReadFromRepository",
                        ],
                        effect=aws_iam.Effect.ALLOW,
                        resources=[
                            self.node.try_get_context(
                                "tbg-codeartifact-python-repository-arn"
                            )
                        ],
                    ),
                    aws_iam.PolicyStatement(
                        actions=["sts:GetServiceBearerToken"],
                        conditions={
                            "StringEquals": {
                                "sts:AWSServiceName": "codeartifact.amazonaws.com"
                            }
                        },
                        effect=aws_iam.Effect.ALLOW,
                        resources=["*"],
                    ),
                ]
            ),
        )

        self.pipeline.add_stage(
            stage=cdk.stages.prod_stage.ProdStage(
                scope=self,
                id="ProdStage",
                env=aws_cdk.Environment(account="538493872512", region="us-east-1"),
                stage_name=namer.get_name("ProdStage"),
                aws_config=aws_config,
                permissions_boundary=self._create_permissions_boundary_managed_policy(
                    aws_config=aws_config, namer=namer
                ),
                sentry_ingest_ips=sentry_ingest_ips,
                slack_api_ips=slack_api_ips,
            ),
        )

    def _create_permissions_boundary_managed_policy(
        self, aws_config: AwsConfig, namer: tbg_cdk.IResourceNamer
    ) -> None:
        self.permissions_boundary = aws_iam.ManagedPolicy(
            scope=self,
            id="PermissionsBoundary",
            description="Permissions boundary for the alarm notifier stack",
            managed_policy_name=namer.get_name("PermissionsBoundary"),
            statements=[
                aws_iam.PolicyStatement(
                    actions=[
                        "*",
                    ],
                    conditions={
                        "StringEquals": {
                            "aws:ResourceTag/ApplicationName": "Alarm Notifier",
                            "aws:ResourceTag/Environment": "Development",
                        }
                    },
                    effect=aws_iam.Effect.ALLOW,
                    resources=["*"],
                    sid="AllowApplicationSelfService",
                ),
                aws_iam.PolicyStatement(
                    actions=[
                        "ec2:AssignPrivateIpAddresses",
                        "ec2:CreateNetworkInterface",
                        "ec2:DeleteNetworkInterface",
                        "ec2:DescribeNetworkInterfaces",
                        "ec2:UnassignPrivateIpAddresses",
                    ],
                    effect=aws_iam.Effect.ALLOW,
                    resources=["*"],
                    sid="AllowLambdaVpc",
                ),
                aws_iam.PolicyStatement(
                    actions=["dynamodb:*"],
                    effect=aws_iam.Effect.ALLOW,
                    resources=["*"],
                    sid="AllowDynamoAccessBecauseItDoesNotSupportAbac",
                ),
                aws_iam.PolicyStatement(
                    actions=[
                        "secretsmanager:DescribeSecret",
                        "secretsmanager:GetSecretValue",
                    ],
                    effect=aws_iam.Effect.ALLOW,
                    resources=[
                        aws_config.sentry_dsn_secret_arn,
                        aws_config.slack_alarm_notifier_oauth_token_secret_arn,
                    ],
                    sid="AllowReadingSharedSecrets",
                ),
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
                                stack=self,
                            )
                        }
                    },
                    effect=aws_iam.Effect.DENY,
                    resources=["*"],
                    sid="CreateOrChangeOnlyWithPermissionsBoundary",
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
                            stack=self,
                        )
                    ],
                    sid="NoPermissionBoundaryPolicyEdit",
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


class BuildDevPipelineStack(aws_cdk.Stack):
    def __init__(
        self,
        scope: constructs.Construct,
        id: str,
        *,
        aws_config: AwsConfig,
        namer: tbg_cdk.IResourceNamer,
        sentry_ingest_ips: typing.Sequence[str],
        slack_api_ips: typing.Sequence[str],
        **kwargs
    ):
        super().__init__(scope=scope, id=id, **kwargs)

        self.github_connection = aws_codestarconnections.CfnConnection(
            scope=self,
            id="AlarmNotifierGitHubConnection",
            connection_name="AlarmNotifierGitHubConnection",
            provider_type="GitHub",
        )

        self.pipeline = pipelines.CodePipeline(
            scope=self,
            id="DevPipeline",
            pipeline_name=namer.get_name("AwsAlarmNotifierDevPipeline"),
            synth=pipelines.ShellStep(
                id="Synth",
                commands=[
                    "export ASDF_DIR=~/.asdf",
                    "git clone https://github.com/asdf-vm/asdf.git ~/.asdf --branch v0.13.1",
                    ". $ASDF_DIR/asdf.sh",
                    "asdf plugin add nodejs",
                    "asdf plugin add poetry",
                    "asdf plugin add python",
                    "asdf plugin add awscli",
                    "asdf install",
                    "npm i",
                    "poetry config http-basic.tbg aws $(aws codeartifact get-authorization-token --duration-seconds 3600 --domain tbg --domain-owner 538493872512 --query authorizationToken --output text)",
                    "poetry install --no-root --without=dev",
                    """npx cdk --context codeartifact_authorization_token=`aws codeartifact get-authorization-token --duration-seconds 3600 --domain tbg --domain-owner 538493872512 --query authorizationToken --output text` --app "VERSION=`poetry version --short` poetry run python -m cdk.dev" synth AlarmNotifierPipeline""",
                ],
                input=pipelines.CodePipelineSource.connection(
                    repo_string="collaterate/aws-cloudwatch-alarm-notifier",
                    branch="develop",
                    connection_arn=self.github_connection.attr_connection_arn,
                    action_name=namer.get_name("GitHub"),
                ),
            ),
            synth_code_build_defaults=pipelines.CodeBuildOptions(
                role_policy=[
                    aws_iam.PolicyStatement(
                        actions=[
                            "codeartifact:GetAuthorizationToken",
                            "codeartifact:GetRepositoryEndpoint",
                            "codeartifact:ReadFromRepository",
                        ],
                        effect=aws_iam.Effect.ALLOW,
                        resources=[aws_config.tbg_codeartifact_domain_arn],
                    ),
                    aws_iam.PolicyStatement(
                        actions=[
                            "codeartifact:GetRepositoryEndpoint",
                            "codeartifact:ReadFromRepository",
                        ],
                        effect=aws_iam.Effect.ALLOW,
                        resources=[aws_config.tbg_codeartifact_python_repository_arn],
                    ),
                    aws_iam.PolicyStatement(
                        actions=["sts:GetServiceBearerToken"],
                        conditions={
                            "StringEquals": {
                                "sts:AWSServiceName": "codeartifact.amazonaws.com"
                            }
                        },
                        effect=aws_iam.Effect.ALLOW,
                        resources=["*"],
                    ),
                ]
            ),
        )

        self._create_permissions_boundary_managed_policy(
            aws_config=aws_config, namer=namer
        )

        self.pipeline.add_stage(
            stage=cdk.stages.dev_stage.DevStage(
                scope=self,
                id="DevStage",
                env=aws_cdk.Environment(account="800572224722", region="us-east-1"),
                permissions_boundary=self.permissions_boundary,
                stage_name=namer.get_name("DevStage"),
                aws_config=aws_config,
                sentry_ingest_ips=sentry_ingest_ips,
                slack_api_ips=slack_api_ips,
            ),
        )

    def _create_permissions_boundary_managed_policy(
        self, aws_config: AwsConfig, namer: tbg_cdk.IResourceNamer
    ) -> None:
        self.permissions_boundary = aws_iam.ManagedPolicy(
            scope=self,
            id="PermissionsBoundary",
            description="Permissions boundary for the alarm notifier stack",
            managed_policy_name=namer.get_name("PermissionsBoundary"),
            statements=[
                aws_iam.PolicyStatement(
                    actions=[
                        "*",
                    ],
                    conditions={
                        "StringEquals": {
                            "aws:ResourceTag/ApplicationName": "Alarm Notifier",
                            "aws:ResourceTag/Environment": "Development",
                        }
                    },
                    effect=aws_iam.Effect.ALLOW,
                    resources=["*"],
                    sid="AllowApplicationSelfService",
                ),
                aws_iam.PolicyStatement(
                    actions=[
                        "ec2:AssignPrivateIpAddresses",
                        "ec2:CreateNetworkInterface",
                        "ec2:DeleteNetworkInterface",
                        "ec2:DescribeNetworkInterfaces",
                        "ec2:UnassignPrivateIpAddresses",
                    ],
                    effect=aws_iam.Effect.ALLOW,
                    resources=["*"],
                    sid="AllowLambdaVpc",
                ),
                aws_iam.PolicyStatement(
                    actions=["dynamodb:*"],
                    effect=aws_iam.Effect.ALLOW,
                    resources=["*"],
                    sid="AllowDynamoAccessBecauseItDoesNotSupportAbac",
                ),
                aws_iam.PolicyStatement(
                    actions=[
                        "secretsmanager:DescribeSecret",
                        "secretsmanager:GetSecretValue",
                    ],
                    effect=aws_iam.Effect.ALLOW,
                    resources=[
                        aws_config.sentry_dsn_secret_arn,
                        aws_config.slack_alarm_notifier_oauth_token_secret_arn,
                    ],
                    sid="AllowReadingSharedSecrets",
                ),
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
                                stack=self,
                            )
                        }
                    },
                    effect=aws_iam.Effect.DENY,
                    resources=["*"],
                    sid="CreateOrChangeOnlyWithPermissionsBoundary",
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
                            stack=self,
                        )
                    ],
                    sid="NoPermissionBoundaryPolicyEdit",
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
