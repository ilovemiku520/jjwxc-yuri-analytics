import { redirect } from "next/navigation";

export default async function LegacyWorkPage({ params }: { params: Promise<{ workId: string }> }) {
  redirect(`/novels/${encodeURIComponent((await params).workId)}`);
}
