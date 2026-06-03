"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "sonner";

export default function LoginPage() {
  const router = useRouter();
  const [isRegister, setIsRegister] = useState(false);
  const [tenantName, setTenantName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    try {
      const endpoint = isRegister ? "/api/v1/auth/register" : "/api/v1/auth/login";
      const res = await api.post(endpoint, {
        tenant_name: tenantName,
        username,
        password,
      });
      const data = await res.json();

      if (data.token || data.access_token) {
        const token = data.token || data.access_token;
        api.setToken(token);
        toast.success(isRegister ? "Registration successful" : "Login successful");
        router.push("/chat");
      } else {
        toast.error("No token received from server");
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "An error occurred";
      toast.error(message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-screen items-center justify-center bg-zinc-950">
      <Card className="w-full max-w-md bg-zinc-900 border-zinc-800">
        <CardHeader>
          <CardTitle className="text-center text-zinc-100">
            {isRegister ? "Create Account" : "Sign In"}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="text-sm text-zinc-400 block mb-1">
                Tenant Name
              </label>
              <Input
                value={tenantName}
                onChange={(e) => setTenantName(e.target.value)}
                placeholder="your-tenant"
                className="bg-zinc-800 border-zinc-700 text-zinc-100"
                required
              />
            </div>
            <div>
              <label className="text-sm text-zinc-400 block mb-1">
                Username
              </label>
              <Input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="username"
                className="bg-zinc-800 border-zinc-700 text-zinc-100"
                required
              />
            </div>
            <div>
              <label className="text-sm text-zinc-400 block mb-1">
                Password
              </label>
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="password"
                className="bg-zinc-800 border-zinc-700 text-zinc-100"
                required
              />
            </div>
            <Button
              type="submit"
              className="w-full bg-zinc-200 text-zinc-900 hover:bg-zinc-300"
              disabled={loading}
            >
              {loading
                ? "Loading..."
                : isRegister
                  ? "Register"
                  : "Sign In"}
            </Button>
          </form>
          <div className="mt-4 text-center">
            <button
              onClick={() => setIsRegister(!isRegister)}
              className="text-sm text-zinc-400 hover:text-zinc-200 underline"
            >
              {isRegister
                ? "Already have an account? Sign in"
                : "Don't have an account? Register"}
            </button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
