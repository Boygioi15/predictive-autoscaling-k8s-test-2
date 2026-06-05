import textApi from "@/api/textApi";
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
import { Textarea } from "@/components/ui/textarea";
import { Database, HelpCircle } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

const defaultText =
  "This memory-pressure workload keeps a working set alive briefly so concurrent requests show up as real RAM pressure.";

const TextPressureCard = () => {
  const [text, setText] = useState(defaultText);
  const [chunkSizeKb, setChunkSizeKb] = useState(256);
  const [chunkCount, setChunkCount] = useState(12);
  const [holdMs, setHoldMs] = useState(25);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleRunPressure = async () => {
    if (!text.trim()) {
      toast.error("Please enter sample text");
      return;
    }

    try {
      setLoading(true);
      setResult(null);

      const response = await textApi.createMemoryPressure({
        text,
        chunkSizeKb,
        chunkCount,
        holdMs,
      });
      setResult(response.data);
    } catch (error) {
      toast.error("Failed to call the memory-pressure endpoint");
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
          <Database className="w-5 h-5 text-amber-500" />
          <CardTitle>Memory pressure</CardTitle>
        </div>
        <CardDescription>
          Create a working set in RAM using chunk size, chunk count, and hold
          time.
        </CardDescription>
      </CardHeader>

      <CardContent className="flex flex-1 flex-col gap-4">
        <div className="space-y-2">
          <Label htmlFor="pressure-text">Sample text</Label>
          <Textarea
            id="pressure-text"
            rows={4}
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={loading}
          />
        </div>

        <div className="grid grid-cols-1 gap-3 md:hidden">
          <div className="space-y-2">
            <Label htmlFor="chunk-size-mobile">Chunk size (KiB)</Label>
            <Input
              id="chunk-size-mobile"
              type="number"
              value={chunkSizeKb}
              onChange={(e) => setChunkSizeKb(Number(e.target.value))}
              disabled={loading}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="chunk-count-mobile">Chunk count</Label>
            <Input
              id="chunk-count-mobile"
              type="number"
              value={chunkCount}
              onChange={(e) => setChunkCount(Number(e.target.value))}
              disabled={loading}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="hold-time-mobile">Hold time (ms)</Label>
            <Input
              id="hold-time-mobile"
              type="number"
              value={holdMs}
              onChange={(e) => setHoldMs(Number(e.target.value))}
              disabled={loading}
            />
          </div>
        </div>

        <div className="hidden gap-2 md:grid md:grid-cols-3">
          <Label htmlFor="chunk-size" className="leading-snug">
            Chunk size (KiB)
          </Label>
          <Label htmlFor="chunk-count" className="leading-snug">
            Chunk count
          </Label>
          <Label htmlFor="hold-time" className="leading-snug">
            Hold time (ms)
          </Label>
          <Input
            id="chunk-size"
            type="number"
            value={chunkSizeKb}
            onChange={(e) => setChunkSizeKb(Number(e.target.value))}
            disabled={loading}
          />
          <Input
            id="chunk-count"
            type="number"
            value={chunkCount}
            onChange={(e) => setChunkCount(Number(e.target.value))}
            disabled={loading}
          />
          <Input
            id="hold-time"
            type="number"
            value={holdMs}
            onChange={(e) => setHoldMs(Number(e.target.value))}
            disabled={loading}
          />
        </div>

        <div className="flex min-h-[10rem] flex-1 flex-col rounded-md bg-muted/50 p-3 text-sm">
          {result === null ? (
            <div className="flex h-full flex-1 items-center justify-center gap-2 text-center text-muted-foreground">
              <HelpCircle className="w-4 h-4" />
              No results yet
            </div>
          ) : (
            <div className="space-y-2 animate-in fade-in zoom-in duration-300">
              <div>
                Working set size:{" "}
                <b>{result.workingSetBytes.toLocaleString()} bytes</b>
              </div>
              <div>
                Chunk configuration: <b>{result.chunkCount}</b> x{" "}
                <b>{result.chunkSizeKb} KiB</b>
              </div>
              <div>
                Hold time: <b>{result.holdMs} ms</b>
              </div>
              <div>
                Unique words: <b>{result.uniqueWords}</b>
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
          onClick={handleRunPressure}
          disabled={loading}
        >
          {loading ? "Running memory pressure..." : "Run memory pressure"}
        </Button>
      </CardFooter>
    </Card>
  );
};

export default TextPressureCard;
