import { createContext, useContext } from 'react';
export const SettingsEditContext = createContext<(key: string, dirty: boolean) => void>(() => {});
export const useSettingsEdit = () => useContext(SettingsEditContext);
