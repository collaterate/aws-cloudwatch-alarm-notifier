#!/usr/bin/env python3
import os

import aws_cdk
import cdk_nag
import tbg_cdk
import tbg_cdk_nag

import cdk.stacks.prod_stack

app = aws_cdk.App()

prod_namer = tbg_cdk.ResourceNamer(["Prod", "Prv", "UE1"])

prod_stack = cdk.stacks.prod_stack.ProdStack(
    scope=app,
    id="AlarmNotifierProd",
    env=aws_cdk.Environment(account="800572224722", region="us-east-1"),
    namer=prod_namer.with_prefix("AlarmNotifier"),
    stack_name=prod_namer.get_name("AlarmNotifier"),
    termination_protection=True,
)

aws_cdk.Aspects.of(app).add(
    tbg_cdk.tbg_aspects.SetRemovalPolicy(policy=aws_cdk.RemovalPolicy.DESTROY)
)

aws_cdk.Aspects.of(app).add(cdk_nag.AwsSolutionsChecks(verbose=True))
aws_cdk.Aspects.of(app).add(tbg_cdk_nag.TbgSolutionsChecks(verbose=True))

aws_cdk.Tags.of(prod_stack).add("ApplicationName", "Alarm Notifier")
aws_cdk.Tags.of(prod_stack).add("Environment", "Production")
aws_cdk.Tags.of(prod_stack).add("Region", "us-east-1")

aws_cdk.Tags.of(app).add("ApplicationVersion", os.getenv("VERSION"))

app.synth()
