import ioApi from "@/api/IOApi";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { HelpCircle, Upload } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

const IOWriteCard = () => {
  const [fileId, setFileId] = useState("slot-0");
  const [sizeKb, setSizeKb] = useState(256);
  const [segments, setSegments] = useState(4);
  const [holdMs, setHoldMs] = useState(10);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleWrite = async () => {
    try {
      setLoading(true);
      setResult(null);

      const response = await ioApi.writeFile({
        fileId,
        sizeKb,
        segments,
        holdMs,
      });
      setResult(response.data);
    } catch (error) {
      toast.error("Failed to write the workload file");
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card className="flex flex-col relative h-full">
      {loading && (
        <div className="absolute inset-0 bg-background/50 backdrop-blur-sm z-50 flex items-center justify-center rounded-lg">
          <span className="animate-spin text-primary text-2xl">⏳</span>
        </div>
      )}

      <CardHeader>
        <div className="flex items-center gap-2">
          <Upload className="w-5 h-5 text-emerald-500" />
          <CardTitle>File write</CardTitle>
        </div>
        <CardDescription>
          Write a fixed payload to the mounted volume to simulate file I/O
          write.
        </CardDescription>
      </CardHeader>

      <CardContent className="flex flex-1 flex-col gap-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="space-y-2">
            <Label>File ID</Label>
            <Input
              value={fileId}
              onChange={(e) => setFileId(e.target.value)}
              disabled={loading}
            />
          </div>
          <div className="space-y-2">
            <Label>Size (KiB)</Label>
            <Input
              type="number"
              value={sizeKb}
              onChange={(e) => setSizeKb(Number(e.target.value))}
              disabled={loading}
            />
          </div>
          <div className="space-y-2">
            <Label>Segments</Label>
            <Input
              type="number"
              value={segments}
              onChange={(e) => setSegments(Number(e.target.value))}
              disabled={loading}
            />
          </div>
          <div className="space-y-2">
            <Label>Hold time (ms)</Label>
            <Input
              type="number"
              value={holdMs}
              onChange={(e) => setHoldMs(Number(e.target.value))}
              disabled={loading}
            />
          </div>
        </div>

        <div className="flex min-h-[10rem] flex-1 flex-col rounded-md bg-muted/50 p-3 text-sm">
          {result === null ? (
            <div className="flex h-full flex-1 items-center justify-center gap-2 text-center text-muted-foreground">
              <HelpCircle className="w-4 h-4" /> No results yet
            </div>
          ) : (
            <div className="space-y-2 animate-in fade-in zoom-in duration-300">
              <div>
                Bytes written: <b>{result.bytesWritten.toLocaleString()}</b>
              </div>
              <div>
                Segments: <b>{result.segments}</b>
              </div>
              <div>
                Storage key: <b>{result.storageKey}</b>
              </div>
              <div>
                Checksum: <b>{result.checksum}</b>
              </div>
              <div>
                Processing time: <b>{result.timeTaken}</b>
              </div>
            </div>
          )}
        </div>
      </CardContent>

      <CardFooter>
        <Button
          className="w-full"
          variant="outline"
          onClick={handleWrite}
          disabled={loading}
        >
          {loading ? "Writing..." : "Run write test"}
        </Button>
      </CardFooter>
    </Card>
  );
};

export default IOWriteCard;
