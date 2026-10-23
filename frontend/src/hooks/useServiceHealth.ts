import { useCallback, useEffect, useRef, useState } from "react";

import { ApiClientError, getHealth } from "../api/client";
import type { ServiceStatus } from "../types";

const HEALTH_CHECK_INTERVAL_MS = 30_000;

export function useServiceHealth() {
  const [status, setStatus] = useState<ServiceStatus>("checking");
  const [version, setVersion] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  const checkHealth = useCallback(async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;

    try {
      const response = await getHealth(controller.signal);
      setStatus(response.status.toLowerCase() === "healthy" ? "online" : "offline");
      setVersion(response.version);
    } catch (error) {
      if (error instanceof ApiClientError && error.kind === "aborted") {
        return;
      }

      setStatus("offline");
      setVersion(null);
    }
  }, []);

  useEffect(() => {
    void checkHealth();
    const intervalId = window.setInterval(() => {
      void checkHealth();
    }, HEALTH_CHECK_INTERVAL_MS);

    return () => {
      window.clearInterval(intervalId);
      controllerRef.current?.abort();
    };
  }, [checkHealth]);

  return { status, version, refresh: checkHealth };
}
