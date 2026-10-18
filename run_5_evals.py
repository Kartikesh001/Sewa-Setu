import sys
import time
import json
try:
    from evals.runner import run_evaluation_suite
except ImportError:
    sys.path.insert(0, "./app")
    from evals.runner import run_evaluation_suite

print("=" * 80)
print("STARTING 5 CONSECUTIVE EVALUATION SUITE RUNS")
print("=" * 80)

results = []
for i in range(1, 6):
    print(f"\n---> Executing Run #{i} of 5...")
    start_t = time.time()
    run_record = run_evaluation_suite()
    elapsed = time.time() - start_t
    
    run_id = run_record["run_id"]
    status = run_record["status"]
    pass_rate = run_record["pass_rate"]
    sla_rate = run_record["sla_compliance_rate"]
    duration_ms = run_record["duration_ms"]
    scenarios = run_record["results"]
    
    print(f"Run #{i} Complete:")
    print(f"  Run ID: {run_id}")
    print(f"  Status: {status}")
    print(f"  Pass Rate: {pass_rate:.1f}% ({sum(1 for s in scenarios if s['status'] == 'PASSED')}/{len(scenarios)})")
    print(f"  SLA Rate: {sla_rate:.1f}%")
    print(f"  Duration: {duration_ms} ms (Total wall clock: {elapsed:.2f}s)")
    for s in scenarios:
        print(f"    - [{s['status']}] {s['persona_name']} ({s['scenario_title']}) - {s['turns_count']} turns, {s['duration_ms']}ms")
    
    results.append({
        "run_number": i,
        "run_id": run_id,
        "status": status,
        "pass_rate": pass_rate,
        "sla_rate": sla_rate,
        "duration_ms": duration_ms,
        "scenario_statuses": {s["persona_name"]: s["status"] for s in scenarios}
    })
    time.sleep(1)

print("\n" + "=" * 80)
print("5 CONSECUTIVE RUNS SUMMARY TABLE")
print("=" * 80)
print(f"{'Run #':<7} | {'Run ID':<26} | {'Status':<10} | {'Pass Rate':<10} | {'SLA Rate':<10} | {'Duration (ms)':<14}")
print("-" * 80)
for r in results:
    print(f"{r['run_number']:<7} | {r['run_id']:<26} | {r['status']:<10} | {r['pass_rate']:<10.1f} | {r['sla_rate']:<10.1f} | {r['duration_ms']:<14}")
print("=" * 80)
