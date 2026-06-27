import { useState } from "react";

export function useMessage() {
  const [msg, setMsg] = useState<string | null>(null);
  const [msgType, setMsgType] = useState<"error" | "info" | "success" | null>(null);
  const clearMsg = () => {
    setMsg(null);
    setMsgType(null);
  };
  const setError = (m: string) => {
    setMsg(m);
    setMsgType("error");
  };
  const setInfo = (m: string) => {
    setMsg(m);
    setMsgType("info");
  };
  const setSuccess = (m: string) => {
    setMsg(m);
    setMsgType("success");
  };
  return { msg, msgType, clearMsg, setError, setInfo, setSuccess };
}
