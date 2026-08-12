import { PageHeader } from "@/components/ui";
import { NewOrderForm } from "./NewOrderForm";

export const metadata = { title: "New care plan · Care Plan Platform" };

export default function NewOrderPage() {
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title="New care plan"
        subtitle="Enter patient, provider, and medication details. Generation runs in the background and is grounded in retrieved clinical guidelines."
      />
      <NewOrderForm />
    </div>
  );
}
