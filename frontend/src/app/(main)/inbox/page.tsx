import { redirect } from 'next/navigation';

export default function Page() {
  redirect('/review?view=inbox');
}
