import asyncio
import aiohttp
import time
from collections import Counter

URL = "https://akka-tutor-backend.onrender.com/ask"
TOTAL_REQUESTS = 1000
CONCURRENCY = 50

USER_ID = "f693cc61-710c-46e4-a75d-9574ab02f8a6"
PAYLOAD = {
    "user_id": USER_ID,
    "question": "Explain Newton's first law of motion briefly.",
    "subject": "Physics",
    "grade_level": 10,
    "history": []
}

async def fetch(session, url, request_id):
    start = time.time()
    try:
        async with session.post(url, json=PAYLOAD, timeout=120) as response:
            status = response.status
            await response.text() # Read the body
            duration = time.time() - start
            return {"status": status, "duration": duration, "error": None}
    except Exception as e:
        duration = time.time() - start
        return {"status": None, "duration": duration, "error": str(e)}

async def worker(queue, session, results):
    while True:
        try:
            req_id = queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        
        res = await fetch(session, URL, req_id)
        results.append(res)
        queue.task_done()

async def main():
    print(f"Starting FULL INTEGRATION Load Test...")
    print(f"Target: {URL} (LLM + Vector DB Endpoint)")
    print(f"Total Requests: {TOTAL_REQUESTS}")
    print(f"Concurrency: {CONCURRENCY}\n")

    queue = asyncio.Queue()
    for i in range(TOTAL_REQUESTS):
        queue.put_nowait(i)

    results = []
    start_time = time.time()

    async with aiohttp.ClientSession() as session:
        tasks = []
        for _ in range(CONCURRENCY):
            task = asyncio.create_task(worker(queue, session, results))
            tasks.append(task)
        
        await queue.join()

    total_time = time.time() - start_time
    
    # Calculate metrics
    statuses = Counter([r['status'] for r in results if r['status'] is not None])
    errors = [r['error'] for r in results if r['error'] is not None]
    durations = [r['duration'] for r in results]
    
    avg_duration = sum(durations) / len(durations) if durations else 0
    max_duration = max(durations) if durations else 0
    min_duration = min(durations) if durations else 0
    
    rps = TOTAL_REQUESTS / total_time if total_time > 0 else 0

    print("=" * 40)
    print("LOAD TEST RESULTS")
    print("=" * 40)
    print(f"Total Time Taken:  {total_time:.2f} seconds")
    print(f"Requests/Second:   {rps:.2f} RPS")
    print(f"Avg LLM Resp Time: {avg_duration:.3f} seconds")
    print(f"Min LLM Resp Time: {min_duration:.3f} seconds")
    print(f"Max LLM Resp Time: {max_duration:.3f} seconds")
    print("-" * 40)
    print("Status Codes:")
    for code, count in statuses.items():
        print(f"  HTTP {code}: {count}")
    
    if errors:
        print("-" * 40)
        print(f"Errors Encountered ({len(errors)}):")
        err_counts = Counter(errors)
        for err, count in err_counts.items():
            print(f"  {err}: {count}")

if __name__ == "__main__":
    asyncio.run(main())
