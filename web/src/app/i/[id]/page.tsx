import { notFound } from "next/navigation";
import IndexView from "@/components/index-view";
import { LAB_IDS } from "@/lib/labs";

export default async function IndexPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  // Synthetic labs live under /labs; any other id is checked against the catalogue by the view.
  if (!/^[a-z0-9-]{1,40}$/.test(id) || (LAB_IDS as readonly string[]).includes(id)) notFound();
  return <IndexView indexId={id} />;
}
