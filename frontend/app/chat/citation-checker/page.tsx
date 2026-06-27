import { redirect } from "next/navigation";

export default function CitationCheckerRoutePage() {
  redirect("/chat?mode=verification");
}
