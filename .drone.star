# Build pipelines

PYTHON_VERSIONS = [
    "3.7",
    "3.8",
    "3.9",
    "3.10",
    "3.11",
    "3.12",
    "latest",
]


def main(ctx):
    pipelines = []

    # Run tests
    pipelines += tests()
    pipelines += [{
        "kind": "pipeline",
        "name": "lint",
        "workspace": get_workspace(),
        "steps": [{
            "name": "lint",
            "image": "python:3",
            "commands": [
                "python -V",
                "make lint",
            ]
        }]
    }]

    # Add pypi push pipeline
    pipelines += push_to_pypi()

    # Add notifications
    pipeline_names = [
        pipeline["name"] for pipeline in pipelines
    ]
    pipelines += notify(pipeline_names)

    return pipelines


# Return workspace in the container
def get_workspace():
    return {
        "base": "/app",
        "path": ".",
    }


# Builds a list of all test pipelines to be executed
def tests():
    return [{
        "kind": "pipeline",
        "name": "tests",
        "workspace": get_workspace(),
        "steps": [
            test_step("python:"+version)
            for version in PYTHON_VERSIONS
        ],
    }]


# Builds a single python test step
def test_step(docker_tag, python_cmd="python"):
    return {
        "name": "test {}".format(docker_tag.replace(":", "")),
        "image": docker_tag,
        "commands": [
            "{} -V".format(python_cmd),
            "make clean-all test"
        ],
        "environment": {
            "PIP_CACHE_DIR": ".pip-cache",
        },
    }


# Builds a notify step that will notify when the previous step changes
def notify_step():
    return {
        "name": "notify",
        "image": "drillster/drone-email",
        "settings": {
            "host": {
                "from_secret": "SMTP_HOST",
            },
            "username": {
                "from_secret": "SMTP_USER",
            },
            "password": {
                "from_secret": "SMTP_PASS",
            },
            "from": "drone@iamthefij.com",
        },
        "when": {
            "status": [
                "changed",
                "failure",
            ],
        },
    }


# Builds a notify pipeline that will notify when a dependency fails
def notify(depends_on=None):
    if not depends_on:
        depends_on = ["tests"]

    return [{
        "kind": "pipeline",
        "name": "notify",
        "depends_on": depends_on,
        "trigger": {"status": ["failure"]},
        "steps": [notify_step()]
    }]


# Push package to pypi
def push_to_pypi():
    return [{
        "kind": "pipeline",
        "name": "deploy to pypi",
        "depends_on": ["tests", "lint"],
        "workspace": get_workspace(),
        "trigger": {
            "ref": [
                # "refs/heads/main",
                "refs/tags/v*",
            ],
        },
        "steps": [
            # {
            #     "name": "push to test pypi",
            #     "image": "python:3",
            #     "environment": {
            #         "HATCH_INDEX_USER": {
            #             "from_secret": "PYPI_USERNAME",
            #         },
            #         "HATCH_INDEX_AUTH": {
            #             "from_secret": "TEST_PYPI_PASSWORD",
            #         },
            #     },
            #     "commands": ["make upload-test"],
            # },
            {
                "name": "push to pypi",
                "image": "python:3",
                "environment": {
                    "HATCH_INDEX_USER": {
                        "from_secret": "PYPI_USERNAME",
                    },
                    "HATCH_INDEX_AUTH": {
                        "from_secret": "PYPI_PASSWORD",
                    },
                },
                "commands": ["make upload"],
                "when": {
                    "event": ["tag"],
                },
            },
        ]
    }]

# vim: ft=python
