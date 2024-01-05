import typing

import constructs
import tbg_cdk
from aws_cdk import aws_ec2


class AlarmNotificationFunctionSecurityGroupFactory(typing.Protocol):
    def create(
        self,
        scope: constructs.Construct,
        id: str,
        *,
        namer: tbg_cdk.IResourceNamer,
        vpc: aws_ec2.IVpc,
    ) -> aws_ec2.ISecurityGroup:
        ...
