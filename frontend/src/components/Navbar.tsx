import { Topbar } from "./Topbar";

/**
 * @deprecated — use Topbar. Kept for backwards compat; some tests import Navbar.
 */
export function Navbar(props: { onAddPhone?: () => void }) {
  return <Topbar onAddPhone={props.onAddPhone ?? (() => {})} />;
}
