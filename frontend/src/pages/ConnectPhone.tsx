import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

export function ConnectPhone() {
  const nav = useNavigate();
  useEffect(() => {
    nav("/connect/phone", { replace: true });
  }, [nav]);
  return null;
}
