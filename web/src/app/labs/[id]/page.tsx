import { notFound } from "next/navigation";
import LabView from "@/components/lab-view";
import { LAB_IDS, type LabId } from "@/lib/labs";

export default async function LabPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!(LAB_IDS as readonly string[]).includes(id)) notFound();
  return <LabView labId={id as LabId} />;
}
