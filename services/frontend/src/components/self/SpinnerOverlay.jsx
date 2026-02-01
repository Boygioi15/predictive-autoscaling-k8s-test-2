import { Spinner } from "@/components/ui/spinner";

export default function SpinnerOverlay() {
  return (
    <div className="flex flex-col gap-4 absolute inset-0 bg-black/40 items-center justify-center z-9999 h-full w-full">
      <Spinner className={"size-10 text-blue-500"} />
      <span className="text-gray-200 text-[14px] font-medium">Chờ tí nhé</span>
    </div>
  );
}
