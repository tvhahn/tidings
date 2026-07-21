import { useQuery } from "@tanstack/react-query";
import { queries } from "@/lib/queryConfigs";

export function useS3BackupStatus() {
  return useQuery(queries.s3BackupStatus());
}
