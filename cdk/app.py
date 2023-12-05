#!/usr/bin/env python3
import aws_cdk
import tbg_cdk
from aws_cdk import aws_lambda

import cdk.stacks.build_pipeline_stack

app = aws_cdk.App()

cdk.stacks.build_pipeline_stack.BuildPipelineStack(
    scope=app,
    id="AlarmNotifierPipeline",
    env=aws_cdk.Environment(account="800572224722", region="us-east-1"),
    namer=tbg_cdk.ResourceNamer(["Prod", "Prv", "UE1", "AlarmNotifierPipeline"]),
)

app.synth()
