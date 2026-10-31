import { redirect } from 'next/navigation';

export default function ApprovalsPage() {
  redirect('/review?view=approvals');
}
