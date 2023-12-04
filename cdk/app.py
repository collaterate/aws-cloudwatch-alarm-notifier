#!/usr/bin/env python3
import aws_cdk
import tbg_cdk
from aws_cdk import aws_lambda

import cdk.stacks.build_pipeline_stack

app = aws_cdk.App()

alarm_notifier_code = aws_lambda.Code.from_docker_build(
    path=".",
    build_args={
        "CODEARTIFACT_AUTHORIZATION_TOKEN": app.node.try_get_context(
            "codeartifact_authorization_token"
        ),
        "POETRY_INSTALL_ARGS": "--only=handler",
    },
    file="Dockerfile.alarm_notifier",
)

cdk.stacks.build_pipeline_stack.BuildPipelineStack(
    scope=app,
    id="AlarmNotifierPipeline",
    alarm_notifier_code=alarm_notifier_code,
    env=aws_cdk.Environment(account="800572224722", region="us-east-1"),
    namer=tbg_cdk.ResourceNamer(["Prod", "Prv", "UE1", "AlarmNotifierPipeline"]),
)

app.synth()
