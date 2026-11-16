import React from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';
import { useRoute, useTelemetry } from './hooks';
import { Header } from './components/Panels';
import { Dashboard } from './pages/Dashboard';
import { Admin } from './pages/Admin';
import { Sessions } from './pages/Sessions';
import { Routes } from './pages/Routes';
import { History } from './pages/History';
import { Workouts } from './pages/Workouts';


function App() {
  const route = useRoute();
  const { data, error, history } = useTelemetry();
  return (
    <main>
      <Header version={__APP_VERSION__} data={data} route={route} />
      {route === 'ajustes' ? <Admin /> : route === 'sesiones' ? <Sessions /> : route === 'rutas' ? <Routes data={data} /> : route === 'historial' ? <History />
        : route === 'entrenamientos' ? <Workouts data={data} />
        : <Dashboard data={data} error={error} history={history} />}
    </main>
  );
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);
