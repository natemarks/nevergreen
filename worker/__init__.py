"""On-instance worker code (not CDK infrastructure).

Deployed onto the gpu_worker instance via SimpleAsgStack's `extra_files`
mechanism -- see stack/simple_asg.py -- so the exact tested source here is
what ends up running on the instance, not a hand-duplicated copy embedded
in a shell script.
"""
