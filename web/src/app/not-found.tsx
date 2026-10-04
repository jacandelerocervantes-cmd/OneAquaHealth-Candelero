import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-md space-y-3 p-8 text-center">
      <h1 className="text-lg font-semibold">Page not found</h1>
      <p className="text-sm text-muted">There is nothing at this address.</p>
      <Link href="/" className="inline-block rounded-lg border border-line px-4 py-2 hover:bg-sidebar">
        Start a new question
      </Link>
    </div>
  );
}
