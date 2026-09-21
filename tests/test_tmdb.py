import io
import unittest

from tmdb import TMDBClient, TokenBucketRateLimiter


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class TMDBRateLimitTest(unittest.TestCase):
    def test_token_bucket_spaces_requests_after_its_burst(self):
        clock = FakeClock()
        limiter = TokenBucketRateLimiter(
            requests_per_second=4,
            burst_size=2,
            clock=clock.monotonic,
            sleep=clock.sleep,
        )

        limiter.acquire()
        limiter.acquire()
        limiter.acquire()

        self.assertEqual(clock.sleeps, [0.25])

    def test_client_acquires_a_token_before_each_request(self):
        class CountingLimiter:
            def __init__(self):
                self.calls = 0

            def acquire(self):
                self.calls += 1

        limiter = CountingLimiter()
        client = TMDBClient(
            "test-token",
            transport=lambda _request, timeout: io.BytesIO(b"{}"),
            rate_limiter=limiter,
        )

        client.popular_tv()

        self.assertEqual(limiter.calls, 1)


if __name__ == "__main__":
    unittest.main()
