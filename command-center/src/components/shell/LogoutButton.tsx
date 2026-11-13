import { useState } from 'react';

import { logout } from '@/api/auth';
import { useAuth } from '@/auth/store';
import { LogoutIcon } from '@/components/common/icons';
import { Tip } from '@/components/common/Tip';
import { Button } from '@/components/ui/button';
import { isTraining } from '@/training/mode';

/**
 * «Выйти» (CC-0037) — только там, где был вход (домашняя сеть). С Mac вход не нужен, и выходить
 * не из чего; в тренировке запросы идут в демо — выход там не нужен тоже.
 */
export function LogoutButton() {
  const { required } = useAuth();
  const [busy, setBusy] = useState(false);
  if (!required || isTraining()) return null;
  return (
    <Tip content="Выйти из центра на этом устройстве: дальше — только по паролю">
      <Button
        size="icon"
        aria-label="Выйти"
        data-testid="logout"
        disabled={busy}
        onClick={() => {
          setBusy(true);
          void logout().finally(() => setBusy(false));
        }}
      >
        <LogoutIcon className="size-[17px]" />
      </Button>
    </Tip>
  );
}
