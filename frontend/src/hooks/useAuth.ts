import { useCallback, useEffect, useState } from "react";

import {
  ApiClientError,
  getCurrentUser,
  login as loginRequest,
  logout as logoutRequest,
  register as registerRequest,
} from "../api/client";
import type { AuthUser } from "../types";

export function useAuth() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getCurrentUser(controller.signal)
      .then(setUser)
      .catch((reason: unknown) => {
        if (!(reason instanceof ApiClientError && reason.status === 401)) {
          setError("暂时无法连接登录服务，请确认后端和数据库已经启动。");
        }
      })
      .finally(() => setIsLoading(false));
    return () => controller.abort();
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    setError(null);
    try {
      const nextUser = await loginRequest(username, password);
      setUser(nextUser);
      return true;
    } catch (reason) {
      setError(reason instanceof ApiClientError ? reason.message : "登录失败，请稍后重试。");
      return false;
    }
  }, []);

  const register = useCallback(
    async (username: string, password: string, displayName: string) => {
      setError(null);
      try {
        const nextUser = await registerRequest(username, password, displayName);
        setUser(nextUser);
        return true;
      } catch (reason) {
        setError(reason instanceof ApiClientError ? reason.message : "注册失败，请稍后重试。");
        return false;
      }
    },
    []
  );

  const logout = useCallback(async () => {
    setError(null);
    try {
      await logoutRequest();
    } catch {
      setError("退出请求未送达服务器；本地登录状态已清除。");
    } finally {
      setUser(null);
    }
  }, []);

  const expireSession = useCallback(() => {
    setUser(null);
    setError("登录已过期，请重新登录。");
  }, []);

  return { user, isLoading, error, setError, login, register, logout, expireSession };
}
