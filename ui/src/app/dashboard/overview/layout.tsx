import { redirect } from 'next/navigation';

export default function OverviewRedirectLayout() {
  redirect('/dashboard/algo');
}
