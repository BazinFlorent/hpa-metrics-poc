
import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE_URL = __ENV.BASE_URL ||
  'http://hpa-metrics-poc-svc.hpa-metrics-poc.svc.cluster.local';

export const options = {
  scenarios: {
    charge_constante: {
      executor: 'constant-arrival-rate',
      rate: 15,
      timeUnit: '1s',
      duration: '3m',
      preAllocatedVUs: 10,
      maxVUs: 30,
    },
  },
};

export default function () {
  const response = http.get(
    `${BASE_URL}/work?mode=cpu&duration_ms=100`,
    {
      headers: {
        Connection: 'close',
      },
    }
  );

  check(response, {
    'HTTP 200': (r) => r.status === 200,
  });
}
