import aws_cdk
import constructs
import tbg_cdk
from aws_cdk import pipelines, aws_iam, aws_codestarconnections

import cdk.stages.dev_stage


class BuildPipelineStack(aws_cdk.Stack):
    def __init__(
        self,
        scope: constructs.Construct,
        id: str,
        *,
        namer: tbg_cdk.IResourceNamer,
        **kwargs
    ):
        super().__init__(scope=scope, id=id, **kwargs)

        self.github_connection = aws_codestarconnections.CfnConnection(
            scope=self,
            id="AlarmNotifierConnectionToGitHub",
            connection_name="AlarmNotifierConnectionToGitHub",
            provider_type="GitHub",
        )

        self.pipeline = pipelines.CodePipeline(
            scope=self,
            id="BuildDevPipeline",
            pipeline_name=namer.get_name("AwsAlarmNotifier"),
            synth=pipelines.ShellStep(
                id="Synth",
                commands=[
                    "export ASDF_DIR=~/.asdf",
                    "git clone https://github.com/asdf-vm/asdf.git ~/.asdf --branch v0.13.1",
                    ". $ASDF_DIR/asdf.sh",
                    "asdf plugin add nodejs",
                    "asdf plugin add poetry",
                    "asdf plugin add python",
                    "asdf install",
                    "npm i",
                    "poetry config http-basic.tbg aws $(aws codeartifact get-authorization-token --duration-seconds 3600 --domain tbg --domain-owner 538493872512 --query authorizationToken --output text)",
                    "poetry install",
                    "npx cdk --context codeartifact_authorization_token=`aws codeartifact get-authorization-token --duration-seconds 3600 --domain tbg --domain-owner 538493872512 --query authorizationToken --output text` synth",
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
                            "arn:aws:codeartifact:us-east-1:538493872512:domain/tbg"
                        ],
                    ),
                    aws_iam.PolicyStatement(
                        actions=[
                            "codeartifact:GetRepositoryEndpoint",
                            "codeartifact:ReadFromRepository",
                        ],
                        effect=aws_iam.Effect.ALLOW,
                        resources=[
                            "arn:aws:codeartifact:us-east-1:538493872512:repository/tbg/python"
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
            stage=cdk.stages.dev_stage.DevStage(
                scope=self,
                id="DevStage",
                env=aws_cdk.Environment(account="800572224722", region="us-east-1"),
                stage_name=namer.get_name("DevStage"),
            ),
            pre=[pipelines.ManualApprovalStep(id="PromoteToDev")],
        )
