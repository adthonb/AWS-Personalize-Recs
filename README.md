# AWS Personalize recommendations

[![Python 3.14](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![uv](https://img.shields.io/badge/uv-DE5FE9?logo=uv&logoColor=white)](https://docs.astral.sh/uv/)
[![AWS Lambda](https://img.shields.io/badge/AWS-Lambda-FF9900?logo=awslambda&logoColor=white)](#package-for-lambda)
[![AWS Personalize](https://img.shields.io/badge/AWS-Personalize-FF9900?logo=awspersonalize&logoColor=white)](https://docs.aws.amazon.com/personalize/latest/dg/what-is-personalize.html)

Two Python Lambda handlers serve item recommendations through API Gateway:

- `lambda-api-personalize.py` calls an existing Amazon Personalize campaign.
- `lambda-api-rds.py` reads recommendations already stored in RDS MySQL.

Both return `{"items": [...]}` and accept the same query parameters. This repo
does not train a model or populate the database. You need existing campaigns
or recommendation tables before serving real requests.

## Quick start

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run:

```bash
uv sync --frozen
uv run --frozen python -m unittest -v
```

uv installs Python 3.14 and the dependencies pinned in `uv.lock`. The tests mock
AWS and MySQL, so they run without credentials or a database. Handler imports
also work without backend configuration; connections open on the first valid
request.

For an offline request-validation check:

```bash
uv run --frozen python -c 'import importlib; handler = importlib.import_module("lambda-api-personalize"); print(handler.lambda_handler({"queryStringParameters": None}, None))'
```

Expect HTTP 400 and `{"code": 400, "msg": "invalid request"}` in the response body.

## Requests

These handlers accept API Gateway proxy events with `queryStringParameters`
and return a proxy response with `statusCode`, JSON `body`, and a JSON content
type. REST API and HTTP API events that supply this field both work.

| Parameter | Required value |
| --- | --- |
| `type` | `rec` for user recommendations, or `related` for similar items |
| `userid` | For `rec`: 1–7 ASCII digits, supplied as a string |
| `sku` | For `related`: exactly 18 uppercase ASCII letters or digits |
| `lang` | A nonempty string prepended to each returned item ID |

`type` selects the operation. If both IDs are supplied, only the ID required
by that operation is used. Missing or invalid parameters return HTTP 400;
an explicit `type` never bypasses ID validation.

With your API Gateway endpoint:

```bash
curl 'https://YOUR_API_ENDPOINT/recommendations?type=rec&userid=123&lang=en'
curl 'https://YOUR_API_ENDPOINT/recommendations?type=related&sku=ABCDEFGHIJKLMNOPQR&lang=en'
```

If the backend returns `A` and `B`, the response body is:

```json
{"items": ["enA", "enB"]}
```

The language value changes output formatting; it does not translate items or
select a model. Related requests sent to Personalize use `th` plus the SKU as
the model's input item ID. RDS lookups use the plain SKU. These conventions
preserve the original dataset format. Empty results return HTTP 200 with
`{"items": []}`.

## Backend configuration

Set environment variables on the Lambda function using your deployment tool
or AWS console. Keep passwords and credentials out of source control.

| Handler | Environment variables |
| --- | --- |
| Personalize | `REC_ARN`: user-recommendation campaign ARN; `RELATED_ARN`: related-item campaign ARN |
| RDS | `RDS_HOST`, `RDS_DB`, `RDS_USER`, `RDS_PASS` |

Each request needs only its selected campaign ARN. Both ARNs refer to custom
campaigns; domain recommender ARNs are not supported by these handlers.

For Personalize, use the Lambda execution role's credentials and grant
`personalize:GetRecommendations` on the selected campaigns. Locally, boto3
uses its normal AWS credential and region discovery. Lambda provides its
runtime region; the AWS CLI profile used by the toolkit is not a Lambda
execution role.

For RDS, the existing tables must expose:

| Table | Lookup column | Result column |
| --- | --- | --- |
| `userRecommend` | `userId` | `items` |
| `itemRelated` | `itemId` | `items` |

`items` must contain a JSON array of strings, such as `["A", "B"]`. Multiple
matching rows are combined in database result order. No matching rows means
an empty list. Queries remain parameterized. The connection is reused and
checked before reuse; each request closes its own buffered cursor, so malformed
stored data cannot leave unread rows on the connection. Reads use autocommit
so later requests do not inherit an old transaction snapshot.

Grant the database user SELECT access to these tables. Configure the Lambda
VPC, subnets, and security groups so it can reach MySQL on port 3306. For
larger concurrent workloads, consider [RDS Proxy](https://docs.aws.amazon.com/lambda/latest/dg/services-rds.html)
and point `RDS_HOST` at its endpoint. An RDS VPC function that also calls AWS
services needs an appropriate network route to those services.

## AWS Agent Toolkit

The toolkit configures AWS MCP access and AWS skills for your coding agent.
It is separate from the Python application environment. Setup follows the
[official AWS instructions](https://raw.githubusercontent.com/aws/agent-toolkit-for-aws/refs/heads/main/setup-instructions/setup.md).
Install the current AWS CLI v2 and uv before running these commands.

Replace `YOUR_PROFILE` with the AWS CLI profile selected for browser login:

```bash
aws configure set region ap-southeast-1 --profile YOUR_PROFILE
aws login --region ap-southeast-1 --profile YOUR_PROFILE
aws sts get-caller-identity --profile YOUR_PROFILE
aws configure agent-toolkit --yes --region us-east-1 --profile YOUR_PROFILE
aws agent-toolkit list-available-skills --region us-east-1 --profile YOUR_PROFILE
```

Complete the browser login yourself. If a browser does not open, use
`aws login --remote --region ap-southeast-1 --profile YOUR_PROFILE`. If the
profile already contains access keys, choose a separate profile for browser
login or deliberately remove the old entries after backing them up.

The toolkit service requires `us-east-1` for installation and catalog queries;
this does not change the application's default region of `ap-southeast-1`.
In each generated `aws-mcp` entry, merge `AWS_MCP_PROXY_PROFILES=YOUR_PROFILE`
into the environment without changing its generated launch settings or
other server entries. For Codex, the configuration is TOML; use the generated
server's environment table rather than pasting JSON into it.

`AGENTS.md` contains the advanced AWS experience rules. Restart your coding
agent after setup so it loads the MCP server and installed skills. Login
credentials last 12 hours and can be renewed for 90 days without another
browser sign-in. To add another account later, run `aws login --profile NAME`,
add that profile to the space-separated `AWS_MCP_PROXY_PROFILES` list, and
restart the agent.

## Package for Lambda

Use the **Python 3.14** runtime. The commands below build an x86_64 Linux ZIP
from the lockfile, following [uv's Lambda packaging guide](https://docs.astral.sh/uv/guides/integration/aws-lambda/).
Start with a fresh build directory for each package so old files are not
included. `mktemp` creates a new directory for each run.

```bash
mkdir -p build dist
recs_build_dir=$(mktemp -d "$PWD/build/lambda.XXXXXX")
uv export --frozen --no-dev --no-emit-project --output-file "$recs_build_dir/requirements.txt"
uv pip install \
  --python-platform x86_64-manylinux2014 \
  --python-version 3.14 \
  --only-binary=:all: \
  --no-compile-bytecode \
  --no-installer-metadata \
  --target "$recs_build_dir/package" \
  --requirements "$recs_build_dir/requirements.txt"
cp api_common.py lambda-api-personalize.py lambda-api-rds.py "$recs_build_dir/package/"
recs_zip_path="$PWD/dist/recommendations-$(basename "$recs_build_dir").zip"
(cd "$recs_build_dir/package" && uv run --frozen python -m zipfile -c "$recs_zip_path" *)
```

For an arm64 function, replace `x86_64-manylinux2014` with
`aarch64-manylinux2014`. This shared package includes both backends and their
dependencies. Select one handler per Lambda function:

| Backend | Lambda handler setting |
| --- | --- |
| Personalize | `lambda-api-personalize.lambda_handler` |
| RDS | `lambda-api-rds.lambda_handler` |

The original filenames are retained. Lambda loads the module by its configured
name; local Python code can use `importlib.import_module` as shown above.
Include `api_common.py` beside the selected handler. Choose a function timeout
that allows backend calls to finish; RDS connection establishment has a
five-second timeout. These commands build the ZIP only and do not deploy it.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| HTTP 400 | Explicit `type`, the full ID format, and nonempty `lang` |
| HTTP 500 | Required environment variables; for RDS, JSON arrays of strings in `items` |
| HTTP 502 | Campaign availability, execution-role permissions, AWS connectivity, or database connectivity |
| Lambda import error | Shared module and dependencies at the ZIP root; runtime and architecture match the package |
| AWS login rejects an existing profile | Static access keys conflict with browser login; use a separate profile |
| AWS MCP cannot find credentials | Matching login profile in `AWS_MCP_PROXY_PROFILES`, renewed credentials, and agent restart |

Handlers log failure categories without credentials or full request events.
Detailed backend errors are not returned to callers. Changes to model recipes,
training, table contents, and cloud deployment are outside this repo's setup.
