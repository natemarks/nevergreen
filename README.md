# cdk-starter

If you're interested in creating  Infrastructure as Code (IaC) projects in AWS,
you've come to the right place. This project is my starting point and I'm happy
to talk about it. 

If you are using this as a GitHub template repository, start with
[CUSTOMIZE.md](./CUSTOMIZE.md).

## Quick Start (Template Consumers)

```console
make .venv
make node_modules
make unit-test
```

If naming changes cause golden-file diffs, run:

```console
make unit-update_golden
make unit-test
```

This project is part pitch and part demonstration. 

There are 4 main reasons to choose CDK in AWS:
1) Free and full support from the cloud provider. AWS will help you with CDK
problems.
2) Delegate state management to AWS Cloudformation. Only deal with templates
and leave the state management and synchronization to battle-tested
cloudformation. By contrast, some other tools will force you to protect and
upgrade your own state data across breaking changes.
3) I can't stress this next one enough: Test hooks make it trivially easy to
test for unintentional template changes. I'm familiar with pytest in python, so
I use that. But CDK supports several languanges and their test hooks. Pick your
favorite and go to town.
4) Programming language support: Having chosen your favorite language for CDK,
you can then extend yor CDK project with the same. In this project, CDK builds
my resources, and I extend that with pyton modules that do things like discover
AMI IDs, external peering targets, etc.
5) Automatic resource tagging: CDK makes it easy to automatically tag all taggable resources. This is important if you have many teams sharing a sandbox account. They make it easy to clean up.

I like tags like:

 - 'owner' ('Nate Marks')
 - 'owner_email' ('npmarks@gmail.com')
 - 'iac_project' ('github.com/natemarks/cdk-starter')



NOTE: GNU Make is useful for automating common project tasks, like testing and
static checks. I also use it to simplify pipeline execution of CDK commands. It
keeps the pipelines clean, and I can test the automation locally.

I enjoy this stuff, so if you have questions, I'll try to help.  Drop me an
email, but be prepared to wait. :)

## Demonstration

CDK deploys and destroys Cloudformation stacks. That's it. I find it useful to
organize my stacks based on whether or not I can deploy them multiple times in
each environment. To demonstrate these two types, I provide a unique stack
module (app_vpc.py) and a multiple stack module (simple_asg.py).

app_vpc.py deploys a VPC with a few of my favorite features. This is a unique
stack, meaning that there will be exactly one app vpc stack in each
environment.

simple_asg.py deploys an autoscaling group, but it can be used many times in
each environment. Multiple stacks like this one support an extra 'stack_id'
attribute to distinguish between the different simple_asg stacks in an
environment. This is obviously not needed for app_vpc which can only exist once
in an environment.

Also, the simple_asg stacks are build on the app_vpc, so they depend upon it.
This dependency is automatic in CDK, but it's nice to demonstrate it.

### CDK Usage

Using 'make cdk-ls' and providing the target environment, cdk prints the stacks
that exist for the dev environment. 
```console
foo@bar:~$ make cdk-ls app_env=dev
   ...
StarterDevAppVpcStack
StarterDevSimpleAsgAaaStack
```

I can use the make target 'cdk-diff' and 'cdk-diff-all' to see if the project
template would change the AWS deployed stack. Note that when I diff the
SimpleAsg stack, CDK automatically figures out that it depends upon th AppVpc
stack. It diffs both. 

If I run the 'cdk-diff-all' target, it diffs every stack in the environment

```console
foo@bar:~$ make cdk-diff app_env=dev stack=StarterDevSimpleAsgAaaStack
 ...
Including dependency stacks: StarterDevAppVpcStack
start: Building 69f29bc9ba86d9acc02d6e91ebe003b265184e8bd7238569531453e75854fbaa:709310380790-us-east-1
success: Built 69f29bc9ba86d9acc02d6e91ebe003b265184e8bd7238569531453e75854fbaa:709310380790-us-east-1
start: Publishing 69f29bc9ba86d9acc02d6e91ebe003b265184e8bd7238569531453e75854fbaa:709310380790-us-east-1
success: Published 69f29bc9ba86d9acc02d6e91ebe003b265184e8bd7238569531453e75854fbaa:709310380790-us-east-1
Hold on while we create a read-only change set to get a diff with accurate replacement information (use --no-change-set to use a less accurate but faster template-only diff)
Stack StarterDevAppVpcStack
There were no differences
start: Building caaf085f9c46d956ec4fc0002e927e7e7febfff7413592436995dbeaa0b3d3de:709310380790-us-east-1
success: Built caaf085f9c46d956ec4fc0002e927e7e7febfff7413592436995dbeaa0b3d3de:709310380790-us-east-1
start: Publishing caaf085f9c46d956ec4fc0002e927e7e7febfff7413592436995dbeaa0b3d3de:709310380790-us-east-1
success: Published caaf085f9c46d956ec4fc0002e927e7e7febfff7413592436995dbeaa0b3d3de:709310380790-us-east-1
Hold on while we create a read-only change set to get a diff with accurate replacement information (use --no-change-set to use a less accurate but faster template-only diff)
Stack StarterDevSimpleAsgAaaStack
There were no differences

✨  Number of stacks with differences: 0
```


'cdk-deploy' and 'cdk-deploy-all' work the same way as 'cdk-diff' and
'cdk-diff-all' above. The deploy commands create or update the specified stacks
deployed in AWS.


I have a 'cdk-destroy' target that works like 'cdk-diff' and 'cdk-deploy'. You
must specify the target stack.  I don't have a 'cdk-destroy-all' because I'm a
coward.

### Pytest Golden Files

CDK test hooks allow me to easily compare a stack template to the expected
template in my pytests. It's a great way to know when a change to the project
unintentially changes a template. To accomplish this, every stack test case has
a golden file. Theses stack test are marked as unit tests. Running 'make
unit-test' will run all such tests. If the project has changed and the actual
template no longer matches the expected template, the test will fail. If the
change is intended, run 'make unit-update-golden'. All the unit test golden
files will be updated. Use git to view and keep/reset the changes.


### Discovery

The environment-specific config files are maintained in the project repo:

 - config/dev/
 - config/staging/
 - config/production/

The data is often generated manually and is fairly static.  However, sometimes I
need to store data from external sources and it's safer and easier to automate
the process of updating parts of the configuration data.  I use the AMI_ID for
the simple_asg stack as an example, just becuase the latest ECS optimized ami
ID changes fairly often, so it's likely to force an update.

To see it in action, set your AWS credentials and run:
```console
foo@bar:~$ make discover app_env=dev
 ...
2025-01-21 08:36:31,544 - {__main__} - {config.discover:update_simple_asg:87} - INFO - updating simple_asg: dev - aaa
```

If you look in the git repository, you should see the file:
config/dev/simple_asg/aaa/simple_asg.json change.  It starts as a simple map in
JSON with a single key. The new version is fleshed out with all the default
values for that dataclass AND a new value for the key: ami_id

The discovery process can be run manually, if you want to carefully manage the
config data changes. Just run the discovery manually and commit the changes to
the repo. The pipeline that runs your CDK commands will just read the
configuration data.  Alternatively, if you don't care about the changes, but
you want the convenience of always using the latest discovered data -  and
perhaps just checking the impact using CDK diff - run the discovery in the
pipeline that runs your CDK commands.



## Contributing

If you'd like to contribute to this project read
[CONTRIBUTING.md](CONTRIBUTING.md).
