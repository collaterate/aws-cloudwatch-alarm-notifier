#!/usr/bin/env python3
import aws_cdk
import tbg_cdk

import cdk.stacks.build_pipeline_stack
from cdk.aws_config import AwsConfig

app = aws_cdk.App()

with open("./aws-config-prod.json") as f:
    aws_config = AwsConfig.model_validate_json(f.read())

cdk.stacks.build_pipeline_stack.BuildProdPipelineStack(
    scope=app,
    id="ProdAlarmNotifierPipeline",
    env=aws_cdk.Environment(account="538493872512", region="us-east-1"),
    aws_config=aws_config,
    namer=tbg_cdk.ResourceNamer(["Prod", "Prv", "UE1", "AlarmNotifierPipeline"]),
)

app.synth()
