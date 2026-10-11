"""Editable cost scenarios, not hosting benchmarks or measured model usage."""
import argparse
import json
import math


def estimate(*, requests, input_tokens, output_tokens, input_rate, output_rate,
             compute, database, planner_fraction=1.0, calls_per_request=1.0, build_cost=0.0):
    values=(requests,input_tokens,output_tokens,input_rate,output_rate,compute,database,
            planner_fraction,calls_per_request,build_cost)
    if any(not math.isfinite(v) or v < 0 for v in values) or planner_fraction > 1:
        raise ValueError('cost assumptions must be finite and nonnegative; fraction must be <= 1')
    per_call = (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
    per_request = per_call * planner_fraction * calls_per_request
    return {'requests':requests,'ai_per_request':per_request,
            'ai_monthly':round(requests*per_request,2),'backend_monthly':round(compute+database,2),
            'build_monthly':round(build_cost,2),
            'runtime_monthly':round(compute+database+requests*per_request+build_cost,2)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--requests',type=int,default=10000)
    parser.add_argument('--input-tokens',type=int,default=4000)
    parser.add_argument('--output-tokens',type=int,default=500)
    parser.add_argument('--input-rate',type=float,default=0.40,help='USD per million input tokens')
    parser.add_argument('--output-rate',type=float,default=1.60,help='USD per million output tokens')
    parser.add_argument('--compute',type=float,default=6)
    parser.add_argument('--database',type=float,default=15.15,help='USD/month, including your storage')
    parser.add_argument('--planner-fraction',type=float,default=1)
    parser.add_argument('--calls-per-request',type=float,default=1)
    parser.add_argument('--build-cost',type=float,default=0,help='Assumed monthly tool generation/evaluation USD')
    args=parser.parse_args()
    values=vars(args)
    try:
        result=estimate(**values)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps({'assumptions':values, 'estimate':result},indent=2))


if __name__ == '__main__':
    main()
