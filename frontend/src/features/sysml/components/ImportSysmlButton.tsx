import { useMutation, useQueryClient } from "@tanstack/react-query"
import { FileUp, Loader2 } from "lucide-react"
import { useRef } from "react"
import { useTranslation } from "react-i18next"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { describeError } from "@/features/cad/format"

import { importSysml, sysmlKeys } from "../queries"

type Props = {
  /** The SysML kernel is running (``importAvailable`` in /api/sysml/status). */
  available: boolean
  /** Called with the id of the new project. */
  onImported: (projectId: string) => void
}

/** Upload a .sysml file: the backend has it parsed and published as a NEW project. */
export function ImportSysmlButton({ available, onImported }: Props) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const mutation = useMutation({
    mutationFn: async (file: File) => importSysml(file.name, await file.text()),
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: sysmlKeys.projects() })
      void queryClient.invalidateQueries({ queryKey: sysmlKeys.status() })
      onImported(result.projectId)
      toast.success(t("sysml.import.done", { name: result.projectName }))
    },
    onError: (error) => toast.error(t("sysml.import.failed"), { description: describeError(error) }),
  })

  return (
    <span title={available ? undefined : t("sysml.import.unavailable")}>
      <input
        ref={input}
        type="file"
        accept=".sysml"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0]
          event.target.value = "" // the same file can be chosen again
          if (file) mutation.mutate(file)
        }}
      />
      <Button
        variant="outline"
        size="sm"
        disabled={!available || mutation.isPending}
        onClick={() => input.current?.click()}
      >
        {mutation.isPending ? <Loader2 className="animate-spin" /> : <FileUp />}
        {mutation.isPending ? t("sysml.import.running") : t("sysml.import.button")}
      </Button>
    </span>
  )
}
