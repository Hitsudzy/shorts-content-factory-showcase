import { Link } from 'react-router';

export function NotFound() {
  return (
    <section>
      <h1 className="mb-2 text-xl font-semibold">Такой страницы нет</h1>
      <Link to="/" className="underline">
        На главную
      </Link>
    </section>
  );
}
