import { FormEvent, useState } from "react";

interface AuthPageProps {
  error: string | null;
  onLogin: (username: string, password: string) => Promise<boolean>;
  onRegister: (
    username: string,
    password: string,
    displayName: string
  ) => Promise<boolean>;
}

export function AuthPage({ error, onLogin, onRegister }: AuthPageProps) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setLocalError(null);
    if (mode === "register" && password !== confirmPassword) {
      setLocalError("两次输入的密码不一致。");
      return;
    }
    setIsSubmitting(true);
    try {
      if (mode === "login") await onLogin(username, password);
      else await onRegister(username, password, displayName);
    } finally {
      setIsSubmitting(false);
    }
  };

  const changeMode = (nextMode: "login" | "register") => {
    setMode(nextMode);
    setLocalError(null);
    setPassword("");
    setConfirmPassword("");
  };

  return (
    <main className="auth-shell">
      <section className="auth-card" aria-label={mode === "login" ? "登录" : "注册"}>
        <div className="auth-brand" aria-hidden="true">🤖</div>
        <h1>星星科技 AI 客服</h1>
        <p className="auth-subtitle">登录后管理属于您的订单、物流和客服工单</p>

        <div className="auth-tabs" role="tablist" aria-label="账号操作">
          <button type="button" className={mode === "login" ? "active" : ""} onClick={() => changeMode("login")}>登录</button>
          <button type="button" className={mode === "register" ? "active" : ""} onClick={() => changeMode("register")}>注册</button>
        </div>

        <form className="auth-form" onSubmit={submit}>
          <label>
            用户名
            <input value={username} onChange={(event) => setUsername(event.target.value)} minLength={3} maxLength={32} autoComplete="username" required placeholder="3-32 位中文、字母、数字或下划线" />
          </label>
          {mode === "register" && (
            <label>
              昵称
              <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} maxLength={64} autoComplete="name" placeholder="不填写则使用用户名" />
            </label>
          )}
          <label>
            密码
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} minLength={8} maxLength={128} autoComplete={mode === "login" ? "current-password" : "new-password"} required placeholder="至少 8 位" />
          </label>
          {mode === "register" && (
            <label>
              确认密码
              <input type="password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} minLength={8} maxLength={128} autoComplete="new-password" required />
            </label>
          )}
          {(localError || error) && <div className="auth-error" role="alert">{localError || error}</div>}
          <button className="auth-submit" type="submit" disabled={isSubmitting}>
            {isSubmitting ? "请稍候..." : mode === "login" ? "登录" : "创建账号并登录"}
          </button>
        </form>
        {mode === "register" && <p className="auth-security">密码经过加盐哈希后保存，系统不会存储您的明文密码。</p>}
      </section>
    </main>
  );
}
